from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..io import read_json, write_json
from ..orchestrator import resolve_task


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


ACTION_COMMANDS: dict[str, list[str]] = {
    "research": ["research", "{project}", "--agent", "{agent}"],
    "structure": ["structure", "{project}", "--agent", "{agent}"],
    "script": ["script", "{project}", "--agent", "{agent}"],
    "shots": ["shots", "{project}", "--agent", "{agent}"],
    "consume_research": ["research", "{project}", "--agent", "manual", "--consume-response"],
    "consume_structure": ["structure", "{project}", "--agent", "manual", "--consume-response"],
    "consume_script": ["script", "{project}", "--agent", "manual", "--consume-response"],
    "consume_shots": ["shots", "{project}", "--agent", "manual", "--consume-response"],
    "optimize_assets": ["optimize-assets", "{project}"],
    "generate_image_prompts": ["generate-image-prompts", "{project}"],
    "contact_sheet": ["contact-sheet", "{project}"],
    "export_image_factory": ["export-image-factory", "{project}"],
    "generate_images": ["generate-media", "{project}", "image"],
    "import_images": ["import-images", "{project}"],
    "validate_assets": ["validate-assets", "{project}"],
    "video_jobs": ["video-jobs", "{project}"],
    "generate_videos": ["generate-media", "{project}", "video"],
    "import_videos": ["import-videos", "{project}"],
    "validate_videos": ["validate-videos", "{project}"],
    "create_variants": ["create-variants", "{project}"],
    "build_timeline": ["build-timeline", "{project}"],
    "render_preview": ["render-preview", "{project}"],
    "render_final": ["render-final-base", "{project}"],
}


ACTION_TASKS: dict[str, str] = {
    "research": "research",
    "structure": "structure",
    "script": "script",
    "shots": "shot_planner",
    "optimize_assets": "asset_optimizer",
    "generate_image_prompts": "image_prompt_writer",
    "export_image_factory": "image_generator",
    "generate_images": "image_generator",
    "video_jobs": "animation_prompt_writer",
    "generate_videos": "video_generator",
    "create_variants": "timeline_builder",
    "build_timeline": "timeline_builder",
    "render_preview": "composition_renderer",
    "render_final": "composition_renderer",
}


class JobManager:
    def __init__(self, workspace: Path, config_getter, orchestrator_getter=None, store=None) -> None:
        self.workspace = Path(workspace).resolve()
        self.config_getter = config_getter
        self.orchestrator_getter = orchestrator_getter
        self.store = store
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._lock = threading.Lock()
        self._reconcile_stale_jobs()

    def state_path(self, project_id: str) -> Path:
        return self.workspace / project_id / "studio_run.json"

    def log_path(self, project_id: str) -> Path:
        return self.workspace / project_id / "studio.log"

    def state(self, project_id: str) -> dict[str, Any]:
        path = self.state_path(project_id)
        if path.exists():
            try:
                payload = read_json(path)
            except Exception:
                payload = {}
        else:
            payload = {}
        process = self._processes.get(project_id)
        if process and process.poll() is None:
            payload["status"] = "running"
            payload["pid"] = process.pid
        return {
            "status": payload.get("status", "idle"),
            "action": payload.get("action"),
            "label": payload.get("label"),
            "started_at": payload.get("started_at"),
            "ended_at": payload.get("ended_at"),
            "return_code": payload.get("return_code"),
            "error": payload.get("error"),
            "pid": payload.get("pid"),
            "routing": payload.get("routing"),
        }

    def log_tail(self, project_id: str, lines: int = 160) -> str:
        path = self.log_path(project_id)
        if not path.exists():
            return ""
        data = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(data[-max(1, min(lines, 1000)):])

    def start(self, project_id: str, action: str, *, agent: str | None = None) -> dict[str, Any]:
        if action not in ACTION_COMMANDS:
            raise ValueError(f"Unknown action: {action}")
        with self._lock:
            running = self._processes.get(project_id)
            if running and running.poll() is None:
                raise RuntimeError("A job is already running for this project")
            config = self.config_getter()
            task_id = ACTION_TASKS.get(action)
            route = None
            if task_id and self.orchestrator_getter is not None:
                context: dict[str, Any] = {}
                if self.store is not None:
                    try:
                        brief = self.store.brief(project_id)
                        context = {
                            "duration_seconds": brief.target_duration_seconds,
                            "topic": brief.topic,
                            "title": brief.title,
                        }
                    except Exception:
                        context = {}
                route = resolve_task(self.orchestrator_getter(), task_id, context)
            command_template = ACTION_COMMANDS[action]
            accepts_agent = any("{agent}" in part for part in command_template)
            if action.startswith("consume_"):
                selected_agent = "manual"
            elif agent:
                selected_agent = agent
            elif config.get("agent_mode") == "mock" and accepts_agent:
                selected_agent = "mock"
            elif route and accepts_agent:
                selected_agent = "manual" if route.get("provider_mode") == "manual" else "mock" if route.get("provider_mode") == "mock" else "routed"
            else:
                selected_agent = config.get("agent_mode", "manual")
            command_parts = [
                part.format(project=project_id, agent=selected_agent)
                for part in command_template
            ]
            command = [sys.executable, "-m", "fde", *command_parts, "--workspace", str(self.workspace)]
            env = os.environ.copy()
            if route:
                env["FDE_LLM_COMMAND"] = str(route.get("command_template") or config.get("command_template") or "")
                env["FDE_LLM_MODEL"] = str(route.get("model", ""))
                env["FDE_LLM_PROVIDER"] = str(route.get("provider", ""))
                env["FDE_LLM_REASONING"] = str(route.get("reasoning_effort", "medium"))
                env["FDE_LLM_TEMPERATURE"] = str(route.get("temperature", 0.2))
                env["FDE_LLM_TIMEOUT"] = str(route.get("timeout_seconds", 900))
                env["FDE_LLM_RETRIES"] = str(route.get("retry_count", 0))
                env["FDE_LLM_FALLBACK_COMMAND"] = str(route.get("fallback_command_template", ""))
                env["FDE_LLM_FALLBACK_MODEL"] = str(route.get("fallback_model", ""))
                env["FDE_LLM_FALLBACK_PROVIDER"] = str(route.get("fallback_provider", ""))
                env["FDE_LLM_FALLBACK_ADAPTER"] = str(route.get("fallback_provider_adapter", ""))
                env["FDE_PROMPT_PACK_ID"] = str(route.get("prompt_pack_id", ""))
                env["FDE_PROMPT_PACK_INSTRUCTIONS"] = str(route.get("prompt_pack_instructions", ""))
                env["FDE_PROVIDER_ADAPTER"] = str(route.get("provider_adapter", ""))
                env["FDE_MEDIA_PROVIDER"] = str(route.get("provider", ""))
                env["FDE_MEDIA_MODEL"] = str(route.get("model", ""))
                env["FDE_MEDIA_TIMEOUT"] = str(route.get("timeout_seconds", 3600))
                env["FDE_MEDIA_RETRIES"] = str(route.get("retry_count", 0))
                env["FDE_MEDIA_COMMAND"] = str(route.get("media_command_template", ""))
                env["FDE_MEDIA_FALLBACK_PROVIDER"] = str(route.get("fallback_provider", ""))
                env["FDE_MEDIA_FALLBACK_MODEL"] = str(route.get("fallback_model", ""))
                env["FDE_MEDIA_FALLBACK_COMMAND"] = str(route.get("fallback_media_command_template", ""))
                env["FDE_RENDER_PROVIDER"] = str(route.get("provider", ""))
                env["FDE_RENDER_FALLBACK_PROVIDER"] = str(route.get("fallback_provider", ""))
            elif config.get("command_template"):
                env["FDE_LLM_COMMAND"] = str(config["command_template"])
            log_path = self.log_path(project_id)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = log_path.open("a", encoding="utf-8")
            log_handle.write(f"\n[{utc_now()}] START {action}\n")
            log_handle.write("$ " + " ".join(command) + "\n\n")
            log_handle.flush()
            process = subprocess.Popen(
                command,
                cwd=Path(__file__).resolve().parents[2],
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                start_new_session=True,
            )
            self._processes[project_id] = process
            state = {
                "status": "running",
                "action": action,
                "label": action.replace("_", " ").title(),
                "started_at": utc_now(),
                "ended_at": None,
                "return_code": None,
                "error": None,
                "pid": process.pid,
                "routing": ({
                    "task_id": task_id,
                    "provider": route.get("provider"),
                    "provider_label": route.get("provider_label"),
                    "model": route.get("model"),
                    "reasoning_effort": route.get("reasoning_effort"),
                    "fallback_provider": route.get("fallback_provider"),
                    "fallback_model": route.get("fallback_model"),
                    "prompt_pack": route.get("prompt_pack_label"),
                    "capability": route.get("capability"),
                    "adapter": route.get("provider_adapter"),
                    "matched_rule": route.get("matched_rule"),
                } if route else None),
            }
            write_json(self.state_path(project_id), state)
            thread = threading.Thread(
                target=self._wait_for_job,
                args=(project_id, process, log_handle, state),
                daemon=True,
            )
            thread.start()
            return state

    def stop(self, project_id: str) -> dict[str, Any]:
        with self._lock:
            process = self._processes.get(project_id)
            if not process or process.poll() is not None:
                state = self.state(project_id)
                if state["status"] == "running":
                    state["status"] = "interrupted"
                    state["ended_at"] = utc_now()
                    write_json(self.state_path(project_id), state)
                return state
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except Exception:
                process.terminate()
            return {**self.state(project_id), "status": "stopping"}

    def _wait_for_job(self, project_id: str, process: subprocess.Popen[str], log_handle, state: dict[str, Any]) -> None:
        return_code = process.wait()
        log_handle.write(f"\n[{utc_now()}] END return_code={return_code}\n")
        log_handle.close()
        status = "completed" if return_code == 0 else "waiting" if return_code == 2 else "failed"
        state.update({
            "status": status,
            "ended_at": utc_now(),
            "return_code": return_code,
            "error": None if return_code in {0, 2} else f"Command exited with status {return_code}",
        })
        write_json(self.state_path(project_id), state)
        with self._lock:
            self._processes.pop(project_id, None)

    def _reconcile_stale_jobs(self) -> None:
        if not self.workspace.exists():
            return
        for path in self.workspace.glob("*/studio_run.json"):
            try:
                state = read_json(path)
            except Exception:
                continue
            if state.get("status") == "running":
                state["status"] = "interrupted"
                state["ended_at"] = utc_now()
                state["error"] = "Studio restarted while this job was running"
                write_json(path, state)
