from __future__ import annotations

import json
import os
import shlex
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .io import atomic_write_text, read_json, write_json
from .providers.anthropic_api import run_structured as run_anthropic_structured
from .providers.gemini_api import run_structured as run_gemini_structured
from .providers.grok_cli import run_structured as run_grok_structured
from .providers.kimi_api import run_structured as run_kimi_structured
from .models import (
    Chapter,
    Claim,
    DocumentaryScript,
    DocumentaryStructure,
    NarrationSegment,
    ResearchDossier,
    Shot,
    ShotPlan,
    SourceRef,
)


class AgentPending(RuntimeError):
    """Raised when a manual response is required."""


class StructuredAgent(ABC):
    @abstractmethod
    def run(self, *, stage: str, prompt: str, output_model: type[BaseModel], request_dir: Path) -> BaseModel:
        raise NotImplementedError


class ManualAgent(StructuredAgent):
    def __init__(self, consume_response: bool = False) -> None:
        self.consume_response = consume_response

    def run(self, *, stage: str, prompt: str, output_model: type[BaseModel], request_dir: Path) -> BaseModel:
        request_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = request_dir / f"{stage}_prompt.md"
        response_path = request_dir / f"{stage}_response.json"
        schema_path = request_dir / f"{stage}_schema.json"
        atomic_write_text(prompt_path, prompt)
        write_json(schema_path, output_model.model_json_schema())
        if self.consume_response and response_path.exists():
            return output_model.model_validate(read_json(response_path))
        raise AgentPending(
            f"Manual response required. Prompt: {prompt_path}\n"
            f"Save JSON to: {response_path}\n"
            "Then rerun with --consume-response."
        )


class CommandAgent(StructuredAgent):
    def __init__(self, command_template: str | None = None) -> None:
        self.command_template = command_template or os.environ.get("FDE_LLM_COMMAND", "")
        if not self.command_template:
            raise ValueError("set FDE_LLM_COMMAND or pass a command template")

    def run(self, *, stage: str, prompt: str, output_model: type[BaseModel], request_dir: Path) -> BaseModel:
        request_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = request_dir / f"{stage}_prompt.md"
        output_path = request_dir / f"{stage}_response.json"
        pack_id = os.environ.get("FDE_PROMPT_PACK_ID", "")
        pack_instructions = os.environ.get("FDE_PROMPT_PACK_INSTRUCTIONS", "").strip()
        routed_prompt = prompt
        if pack_instructions:
            routed_prompt = f"# Active prompt pack: {pack_id or 'workspace default'}\n\n{pack_instructions}\n\n---\n\n{prompt}"
        atomic_write_text(prompt_path, routed_prompt)
        model = os.environ.get("FDE_LLM_MODEL", "")
        fallback_model = os.environ.get("FDE_LLM_FALLBACK_MODEL", "")
        reasoning = os.environ.get("FDE_LLM_REASONING", "medium")
        temperature = os.environ.get("FDE_LLM_TEMPERATURE", "0.2")
        timeout = max(1, int(float(os.environ.get("FDE_LLM_TIMEOUT", "900") or 900)))
        retries = max(0, int(float(os.environ.get("FDE_LLM_RETRIES", "0") or 0)))
        fallback_template = os.environ.get("FDE_LLM_FALLBACK_COMMAND", "").strip()
        attempts: list[tuple[str, str, str]] = [
            (self.command_template, model, f"primary attempt {attempt + 1}") for attempt in range(retries + 1)
        ]
        if fallback_template:
            attempts.append((fallback_template, fallback_model or model, "fallback"))
        failures: list[str] = []
        for template, selected_model, label in attempts:
            output_path.unlink(missing_ok=True)
            command = template.format(
                prompt=shlex.quote(str(prompt_path)), output=shlex.quote(str(output_path)),
                model=shlex.quote(selected_model), reasoning=shlex.quote(reasoning),
                temperature=shlex.quote(str(temperature)), timeout=shlex.quote(str(timeout)),
                stage=shlex.quote(stage),
            )
            try:
                completed = subprocess.run(command, shell=True, text=True, capture_output=True, timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                failures.append(f"{label}: timed out after {timeout}s ({exc})")
                continue
            if completed.returncode != 0:
                failures.append(f"{label}: command failed ({completed.returncode})\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")
                continue
            if not output_path.exists() and completed.stdout.strip():
                atomic_write_text(output_path, completed.stdout.strip())
            if not output_path.exists():
                failures.append(f"{label}: command produced no response file or stdout JSON")
                continue
            try:
                return output_model.model_validate(read_json(output_path))
            except Exception as exc:
                failures.append(f"{label}: invalid structured response: {exc}")
        raise RuntimeError("all routed agent attempts failed\n\n" + "\n\n".join(failures))


class GrokCLIAgent(StructuredAgent):
    """Native Grok Build CLI adapter with streaming-JSON recovery."""

    def run(self, *, stage: str, prompt: str, output_model: type[BaseModel], request_dir: Path) -> BaseModel:
        request_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = request_dir / f"{stage}_prompt.md"
        output_path = request_dir / f"{stage}_response.json"
        schema_path = request_dir / f"{stage}_schema.json"
        pack_id = os.environ.get("FDE_PROMPT_PACK_ID", "")
        pack_instructions = os.environ.get("FDE_PROMPT_PACK_INSTRUCTIONS", "").strip()
        routed_prompt = prompt
        if pack_instructions:
            routed_prompt = f"# Active prompt pack: {pack_id or 'workspace default'}\n\n{pack_instructions}\n\n---\n\n{prompt}"
        atomic_write_text(prompt_path, routed_prompt)
        schema = output_model.model_json_schema()
        write_json(schema_path, schema)
        timeout = max(1, int(float(os.environ.get("FDE_LLM_TIMEOUT", "1800") or 1800)))
        retries = max(0, int(float(os.environ.get("FDE_LLM_RETRIES", "0") or 0)))
        model = os.environ.get("FDE_LLM_MODEL", "authenticated-default")
        failures: list[str] = []
        for attempt in range(retries + 1):
            try:
                value = run_grok_structured(
                    prompt=routed_prompt, schema=schema, destination=output_path,
                    cwd=request_dir.parent, model=model, timeout=timeout,
                )
                return output_model.model_validate(value)
            except Exception as exc:
                failures.append(f"attempt {attempt + 1}: {exc}")
        raise RuntimeError("all Grok CLI attempts failed\n" + "\n".join(failures))


class RoutedAgent(StructuredAgent):
    """Provider-agnostic structured executor used by Studio task routes."""

    def __init__(self, context: dict[str, Any], consume_response: bool = False) -> None:
        self.context = context
        self.consume_response = consume_response

    def run(self, *, stage: str, prompt: str, output_model: type[BaseModel], request_dir: Path) -> BaseModel:
        request_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = request_dir / f"{stage}_prompt.md"
        output_path = request_dir / f"{stage}_response.json"
        schema_path = request_dir / f"{stage}_schema.json"
        pack_id = os.environ.get("FDE_PROMPT_PACK_ID", "")
        pack_instructions = os.environ.get("FDE_PROMPT_PACK_INSTRUCTIONS", "").strip()
        routed_prompt = prompt
        if pack_instructions:
            routed_prompt = f"# Active prompt pack: {pack_id or 'workspace default'}\n\n{pack_instructions}\n\n---\n\n{prompt}"
        atomic_write_text(prompt_path, routed_prompt)
        schema = output_model.model_json_schema()
        write_json(schema_path, schema)
        timeout = max(1, int(float(os.environ.get("FDE_LLM_TIMEOUT", "900") or 900)))
        retries = max(0, int(float(os.environ.get("FDE_LLM_RETRIES", "0") or 0)))
        primary = {
            "provider": os.environ.get("FDE_LLM_PROVIDER", ""),
            "adapter": os.environ.get("FDE_PROVIDER_ADAPTER", "command"),
            "model": os.environ.get("FDE_LLM_MODEL", ""),
            "template": os.environ.get("FDE_LLM_COMMAND", ""),
        }
        fallback = {
            "provider": os.environ.get("FDE_LLM_FALLBACK_PROVIDER", ""),
            "adapter": os.environ.get("FDE_LLM_FALLBACK_ADAPTER", ""),
            "model": os.environ.get("FDE_LLM_FALLBACK_MODEL", ""),
            "template": os.environ.get("FDE_LLM_FALLBACK_COMMAND", ""),
        }
        attempts = [primary | {"label": f"primary attempt {index + 1}"} for index in range(retries + 1)]
        if fallback["provider"] and fallback["provider"] != primary["provider"]:
            attempts.append(fallback | {"label": "fallback"})
        failures: list[str] = []
        for item in attempts:
            output_path.unlink(missing_ok=True)
            try:
                value = self._execute(
                    item=item, stage=stage, prompt=routed_prompt, prompt_path=prompt_path,
                    output_path=output_path, schema=schema, output_model=output_model,
                    request_dir=request_dir, timeout=timeout,
                )
                return output_model.model_validate(value)
            except AgentPending:
                raise
            except Exception as exc:
                failures.append(f"{item['label']} ({item['provider'] or item['adapter']}): {exc}")
        raise RuntimeError("all routed agent attempts failed\n\n" + "\n\n".join(failures))

    def _execute(
        self, *, item: dict[str, str], stage: str, prompt: str, prompt_path: Path,
        output_path: Path, schema: dict[str, Any], output_model: type[BaseModel],
        request_dir: Path, timeout: int,
    ) -> dict[str, Any]:
        adapter = item.get("adapter") or "command"
        model = item.get("model") or ""
        reasoning = os.environ.get("FDE_LLM_REASONING", "medium")
        if adapter == "grok_cli":
            return run_grok_structured(
                prompt=prompt, schema=schema, destination=output_path,
                cwd=request_dir.parent, model=model or "authenticated-default", timeout=timeout,
            )
        if adapter == "anthropic_api":
            return run_anthropic_structured(
                prompt=prompt, schema=schema, model=model or "claude-sonnet-5",
                timeout=timeout, reasoning_effort=reasoning,
            )
        if adapter == "kimi_api":
            return run_kimi_structured(
                prompt=prompt, schema=schema, model=model or "kimi-k3",
                timeout=timeout, reasoning_effort=reasoning,
            )
        if adapter == "gemini_api":
            return run_gemini_structured(
                prompt=prompt, schema=schema, model=model or "gemini-3.5-flash",
                timeout=timeout, reasoning_effort=reasoning,
            )
        if adapter in {"command", "custom_cli"}:
            template = item.get("template", "").strip()
            if not template:
                raise RuntimeError("structured command template is not configured")
            return self._command_once(
                template=template, stage=stage, prompt_path=prompt_path,
                output_path=output_path, model=model, timeout=timeout,
            )
        if adapter == "mock":
            value = MockAgent(self.context).run(stage=stage, prompt=prompt, output_model=output_model, request_dir=request_dir)
            return value.model_dump(mode="json")
        if adapter == "manual":
            value = ManualAgent(consume_response=self.consume_response).run(
                stage=stage, prompt=prompt, output_model=output_model, request_dir=request_dir
            )
            return value.model_dump(mode="json")
        raise RuntimeError(f"Unsupported structured adapter: {adapter}")

    @staticmethod
    def _command_once(
        *, template: str, stage: str, prompt_path: Path, output_path: Path,
        model: str, timeout: int,
    ) -> dict[str, Any]:
        command = template.format(
            prompt=shlex.quote(str(prompt_path)), output=shlex.quote(str(output_path)),
            model=shlex.quote(model), reasoning=shlex.quote(os.environ.get("FDE_LLM_REASONING", "medium")),
            temperature=shlex.quote(os.environ.get("FDE_LLM_TEMPERATURE", "0.2")),
            timeout=shlex.quote(str(timeout)), stage=shlex.quote(stage),
        )
        completed = subprocess.run(command, shell=True, text=True, capture_output=True, timeout=timeout)
        (output_path.parent / f"{stage}-command-output.log").write_text(
            (completed.stdout or "") + "\n" + (completed.stderr or ""), encoding="utf-8"
        )
        if completed.returncode != 0:
            raise RuntimeError(f"command failed ({completed.returncode}): {(completed.stderr or completed.stdout)[-4000:]}")
        if not output_path.exists() and completed.stdout.strip():
            atomic_write_text(output_path, completed.stdout.strip())
        if not output_path.exists():
            raise RuntimeError("command produced no response file or stdout JSON")
        return read_json(output_path)


class MockAgent(StructuredAgent):
    """Deterministic offline agent for demos and tests."""

    def __init__(self, context: dict[str, Any]) -> None:
        self.context = context

    def run(self, *, stage: str, prompt: str, output_model: type[BaseModel], request_dir: Path) -> BaseModel:
        project_id = self.context["project_id"]
        title = self.context["title"]
        duration = float(self.context.get("duration", 480))
        if output_model is ResearchDossier:
            return ResearchDossier(
                project_id=project_id,
                summary=f"Offline demonstration dossier for {title}.",
                timeline=["Normal operation", "Anomaly", "Investigation", "Unresolved conclusion"],
                entities=["Investigators", "Operators", "Affected people"],
                evidence=["Operational records", "Technical data", "Recovered evidence"],
                disputed_claims=["Intent and root cause remain unconfirmed in this demo."],
                sources=[SourceRef(source_id="SRC_001", title="Replace with an authoritative source")],
                claims=[Claim(
                    claim_id="CLM_001", statement="A major anomaly occurred.", status="confirmed",
                    source_ids=["SRC_001"], allowed_language="The evidence records a major anomaly.",
                )],
            )
        if output_model is DocumentaryStructure:
            names = [
                "Cold Open", "Before the Failure", "First Warning", "The Critical Turn",
                "Hidden Evidence", "The Search", "Physical Clue", "Competing Explanations",
                "The Investigation Continues", "The Human Ending",
            ]
            chapter_duration = duration / len(names)
            chapters = []
            for index, name in enumerate(names, 1):
                start = (index - 1) * chapter_duration
                end = index * chapter_duration
                chapters.append(Chapter(
                    chapter_id=f"CH{index:02d}", title=name, start_target=start, end_target=end,
                    narrative_purpose=f"Advance the investigation through {name.lower()}.",
                    opening_question=f"What changed during {name.lower()}?",
                    key_information=[f"Key fact for {name}", "Evidence and context"],
                    reveal=f"A new detail changes the understanding of {name.lower()}.",
                    ending_hook="But the next piece of evidence raises a deeper question.",
                ))
            return DocumentaryStructure(project_id=project_id, title=title, chapters=chapters, total_target_seconds=duration)
        if output_model is DocumentaryScript:
            structure = self.context.get("structure")
            chapters = structure.chapters if structure else []
            segments: list[NarrationSegment] = []
            cursor = 0.0
            words = 0
            for chapter in chapters:
                for _local in range(1, 4):
                    text = (
                        f"This is demonstration narration for {chapter.title}. "
                        "It explains the evidence carefully, separates confirmed facts from theory, "
                        "and prepares the next investigative reveal."
                    )
                    seg_duration = (chapter.end_target - chapter.start_target) / 3
                    words += len(text.split())
                    segments.append(NarrationSegment(
                        narration_id=f"NAR_{len(segments)+1:03d}", chapter_id=chapter.chapter_id,
                        text=text, estimated_start=cursor, estimated_duration=seg_duration,
                        mood="investigative", intensity=min(0.95, 0.25 + len(segments) * 0.02),
                        claim_ids=["CLM_001"], pause_after_seconds=0.2,
                    ))
                    cursor += seg_duration
            return DocumentaryScript(
                project_id=project_id, title=title, segments=segments,
                estimated_total_seconds=cursor, estimated_word_count=words,
            )
        if output_model is ShotPlan:
            script = self.context.get("script")
            shots: list[Shot] = []
            for segment in script.segments:
                half = segment.estimated_duration / 2
                for part in range(2):
                    idx = len(shots) + 1
                    visual_types = ["flight_reconstruction", "technical_map", "investigation_room", "atmosphere"]
                    vtype = visual_types[idx % len(visual_types)]
                    shots.append(Shot(
                        shot_id=f"S{idx:03d}", chapter_id=segment.chapter_id,
                        narration_ids=[segment.narration_id], start=segment.estimated_start + part * half,
                        duration=half, visual_purpose=f"Support {segment.narration_id} with a distinct visual beat.",
                        visual_type=vtype, suggested_visual=f"Reusable {vtype.replace('_', ' ')} scene for {segment.chapter_id}",
                        camera="Stable cinematic composition", motion="Subtle controlled movement",
                        overlay_requirements=["time", "evidence label"] if idx % 3 == 0 else [],
                        suspense_function="reveal" if idx % 7 == 0 else "support",
                    ))
            return ShotPlan(project_id=project_id, shots=shots, total_seconds=script.estimated_total_seconds)
        raise ValueError(f"mock agent has no generator for {output_model.__name__}")


def get_agent(kind: str, context: dict[str, Any], consume_response: bool = False) -> StructuredAgent:
    if kind == "manual":
        return ManualAgent(consume_response=consume_response)
    if kind == "command":
        return CommandAgent()
    if kind == "grok":
        return GrokCLIAgent()
    if kind == "routed":
        return RoutedAgent(context, consume_response=consume_response)
    if kind == "mock":
        return MockAgent(context)
    raise ValueError(f"unknown agent: {kind}")
