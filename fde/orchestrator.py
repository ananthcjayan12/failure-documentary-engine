from __future__ import annotations

import copy
import os
import shutil
from pathlib import Path
from typing import Any


PROVIDERS: dict[str, dict[str, Any]] = {
    "codex": {
        "id": "codex",
        "label": "Codex CLI (ChatGPT)",
        "mode": "command",
        "adapter": "command",
        "executable": "codex",
        "description": "ChatGPT-authenticated local reasoning agent.",
        "capabilities": ["structured"],
        "command_template": "codex exec --skip-git-repo-check --model {model} --output-last-message {output} - < {prompt}",
        "media_command_template": "",
        "models": ["gpt-5.6-sol", "gpt-5.6-terra"],
    },
    "claude_code": {
        "id": "claude_code",
        "label": "Claude Code",
        "mode": "command",
        "adapter": "command",
        "executable": "claude",
        "description": "Anthropic subscription-backed command-line reasoning agent.",
        "capabilities": ["structured"],
        "command_template": "claude --model {model} -p \"$(cat {prompt})\" > {output}",
        "media_command_template": "",
        "models": ["claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"],
    },
    "anthropic_api": {
        "id": "anthropic_api",
        "label": "Claude API",
        "mode": "api",
        "adapter": "anthropic_api",
        "executable": None,
        "description": "Anthropic API-backed structured reasoning using ANTHROPIC_API_KEY.",
        "capabilities": ["structured"],
        "command_template": "",
        "media_command_template": "",
        "models": ["claude-sonnet-5", "claude-opus-4-8", "claude-haiku-4-5"],
    },
    "gemini_cli": {
        "id": "gemini_cli",
        "label": "Gemini CLI",
        "mode": "command",
        "adapter": "command",
        "executable": "gemini",
        "description": "Google Gemini subscription-backed command-line reasoning agent.",
        "capabilities": ["structured"],
        "command_template": "gemini -m {model} -p \"$(cat {prompt})\" > {output}",
        "media_command_template": "",
        "models": ["gemini-3.5-pro", "gemini-3.5-flash", "gemini-3-pro"],
    },
    "grok_cli": {
        "id": "grok_cli",
        "label": "Grok Build CLI",
        "mode": "native_cli",
        "adapter": "grok_cli",
        "executable": "grok",
        "description": "SuperGrok/Grok Build CLI for structured reasoning, Imagine images, and image-to-video generation.",
        "capabilities": ["structured", "image", "video"],
        "command_template": "",
        "media_command_template": "",
        "models": ["authenticated-default", "grok-4.5", "grok-4"],
    },
    "custom_cli": {
        "id": "custom_cli",
        "label": "Custom CLI Adapter",
        "mode": "command",
        "adapter": "custom_cli",
        "executable": None,
        "description": "Bring any CLI or local model by configuring structured and media command templates.",
        "capabilities": ["structured", "image", "video", "audio"],
        "command_template": "",
        "media_command_template": "",
        "models": ["your-model-id"],
    },
    "chatgpt_ui": {
        "id": "chatgpt_ui",
        "label": "ChatGPT UI",
        "mode": "manual",
        "adapter": "manual",
        "executable": None,
        "description": "Manual ChatGPT subscription workflow using resumable production packets.",
        "capabilities": ["structured", "image"],
        "command_template": "",
        "media_command_template": "",
        "models": ["GPT-5.6 Thinking", "ChatGPT Images"],
    },
    "grok_ui": {
        "id": "grok_ui",
        "label": "Grok UI",
        "mode": "manual",
        "adapter": "manual",
        "executable": None,
        "description": "Manual Grok Imagine image and image-to-video workflow.",
        "capabilities": ["structured", "image", "video"],
        "command_template": "",
        "media_command_template": "",
        "models": ["Grok Imagine", "Grok 4.5"],
    },
    "manual_upload": {
        "id": "manual_upload",
        "label": "Manual Upload",
        "mode": "manual",
        "adapter": "manual",
        "executable": None,
        "description": "Keep a stage manual while preserving the same resumable pipeline contract.",
        "capabilities": ["image", "video", "audio"],
        "command_template": "",
        "media_command_template": "",
        "models": ["External tool"],
    },
    "hyperframes": {
        "id": "hyperframes",
        "label": "HyperFrames",
        "mode": "local",
        "adapter": "hyperframes",
        "executable": "hyperframes",
        "description": "Frame-accurate HTML/CSS/GSAP browser composition and deterministic MP4 rendering.",
        "capabilities": ["render"],
        "command_template": "",
        "media_command_template": "",
        "models": ["HyperFrames 0.7.62"],
    },
    "ffmpeg": {
        "id": "ffmpeg",
        "label": "FFmpeg Renderer",
        "mode": "local",
        "adapter": "ffmpeg",
        "executable": "ffmpeg",
        "description": "Simple deterministic concatenation renderer and HyperFrames fallback.",
        "capabilities": ["render"],
        "command_template": "",
        "media_command_template": "",
        "models": ["FFmpeg concat"],
    },
    "mock": {
        "id": "mock",
        "label": "Offline Mock",
        "mode": "mock",
        "adapter": "mock",
        "executable": None,
        "description": "Deterministic local generator for testing the complete workflow without provider usage.",
        "capabilities": ["structured", "image", "video", "audio", "render"],
        "command_template": "",
        "media_command_template": "",
        "models": ["Deterministic Demo"],
    },
    "future_api": {
        "id": "future_api",
        "label": "Future API Adapter",
        "mode": "disabled",
        "adapter": "disabled",
        "executable": None,
        "description": "Reserved provider slot for future APIs without pipeline changes.",
        "capabilities": ["structured", "image", "video", "audio"],
        "command_template": "",
        "media_command_template": "",
        "models": ["Not configured"],
    },
}


TASK_DEFINITIONS: list[dict[str, Any]] = [
    {"id": "research", "label": "Research", "stage": 1, "group": "Story", "capability": "structured", "description": "Build the evidence dossier, chronology and source ledger."},
    {"id": "fact_verification", "label": "Fact verification", "stage": 1, "group": "Story", "capability": "structured", "description": "Challenge unsupported claims and separate fact from theory."},
    {"id": "structure", "label": "Story structure", "stage": 2, "group": "Story", "capability": "structured", "description": "Design chapters, reveals, escalation and the human ending."},
    {"id": "script", "label": "Narration script", "stage": 3, "group": "Writing", "capability": "structured", "description": "Write the complete evidence-grounded documentary narration."},
    {"id": "script_qa", "label": "Script QA", "stage": 3, "group": "Writing", "capability": "structured", "description": "Check pacing, repetition, claims and narrative clarity."},
    {"id": "shot_planner", "label": "Shot planner", "stage": 4, "group": "Visual planning", "capability": "structured", "description": "Translate narration into timed visual beats."},
    {"id": "asset_optimizer", "label": "Asset optimizer", "stage": 4, "group": "Visual planning", "capability": "structured", "description": "Compress shots into the smallest reusable master-asset set."},
    {"id": "image_prompt_writer", "label": "Image prompt writer", "stage": 5, "group": "Image factory", "capability": "structured", "description": "Create continuity-aware, animation-ready image prompts."},
    {"id": "image_generator", "label": "Image generator", "stage": 5, "group": "Image factory", "capability": "image", "description": "Generate reusable master stills automatically or through a UI handoff."},
    {"id": "image_qc", "label": "Image QC", "stage": 6, "group": "Image factory", "capability": "structured", "description": "Inspect geometry, continuity, prompt adherence and animation readiness."},
    {"id": "animation_prompt_writer", "label": "Animation prompt writer", "stage": 7, "group": "Video factory", "capability": "structured", "description": "Convert approved stills into restrained motion briefs."},
    {"id": "video_generator", "label": "Video generator", "stage": 7, "group": "Video factory", "capability": "video", "description": "Generate reusable image-to-video master clips."},
    {"id": "video_qc", "label": "Video QC", "stage": 7, "group": "Video factory", "capability": "structured", "description": "Inspect motion stability, identity preservation and loop usefulness."},
    {"id": "voice_generator", "label": "Narration voice", "stage": 8, "group": "Assembly", "capability": "audio", "description": "Create or import the master narration track."},
    {"id": "timeline_builder", "label": "Timeline builder", "stage": 8, "group": "Assembly", "capability": "structured", "description": "Map narration, variants and master clips into the edit."},
    {"id": "composition_renderer", "label": "Composition renderer", "stage": 8, "group": "Assembly", "capability": "render", "description": "Render the deterministic browser composition or FFmpeg fallback."},
    {"id": "final_qc", "label": "Final QC", "stage": 8, "group": "Assembly", "capability": "structured", "description": "Inspect continuity, technical quality and picture-lock readiness."},
]


def route(provider: str, model: str, reasoning: str, temperature: float, timeout: int, retries: int,
          fallback_provider: str, fallback_model: str) -> dict[str, Any]:
    return {
        "provider": provider,
        "model": model,
        "reasoning_effort": reasoning,
        "temperature": temperature,
        "timeout_seconds": timeout,
        "retry_count": retries,
        "fallback_provider": fallback_provider,
        "fallback_model": fallback_model,
        "enabled": True,
    }


DEFAULT_TASK_ROUTES: dict[str, dict[str, Any]] = {
    "research": route("codex", "gpt-5.6-sol", "high", 0.25, 1200, 1, "anthropic_api", "claude-sonnet-5"),
    "fact_verification": route("codex", "gpt-5.6-sol", "high", 0.10, 900, 1, "anthropic_api", "claude-sonnet-5"),
    "structure": route("claude_code", "claude-opus-4-8", "high", 0.55, 1200, 1, "codex", "gpt-5.6-sol"),
    "script": route("claude_code", "claude-opus-4-8", "high", 0.65, 1800, 1, "codex", "gpt-5.6-sol"),
    "script_qa": route("codex", "gpt-5.6-sol", "high", 0.15, 900, 1, "anthropic_api", "claude-sonnet-5"),
    "shot_planner": route("claude_code", "claude-sonnet-5", "medium", 0.45, 1200, 1, "codex", "gpt-5.6-sol"),
    "asset_optimizer": route("codex", "gpt-5.6-terra", "medium", 0.15, 600, 1, "mock", "Deterministic Demo"),
    "image_prompt_writer": route("codex", "gpt-5.6-sol", "medium", 0.55, 900, 1, "anthropic_api", "claude-sonnet-5"),
    "image_generator": route("grok_cli", "authenticated-default", "standard", 0.40, 3600, 1, "chatgpt_ui", "ChatGPT Images"),
    "image_qc": route("codex", "gpt-5.6-sol", "medium", 0.10, 900, 1, "mock", "Deterministic Demo"),
    "animation_prompt_writer": route("codex", "gpt-5.6-sol", "medium", 0.45, 900, 1, "anthropic_api", "claude-sonnet-5"),
    "video_generator": route("grok_cli", "authenticated-default", "standard", 0.40, 3600, 1, "grok_ui", "Grok Imagine"),
    "video_qc": route("codex", "gpt-5.6-sol", "medium", 0.10, 900, 1, "mock", "Deterministic Demo"),
    "voice_generator": route("manual_upload", "External narration", "standard", 0, 0, 0, "manual_upload", "External narration"),
    "timeline_builder": route("codex", "gpt-5.6-terra", "low", 0.10, 600, 1, "mock", "Deterministic Demo"),
    "composition_renderer": route("hyperframes", "HyperFrames 0.7.62", "standard", 0, 14400, 1, "ffmpeg", "FFmpeg concat"),
    "final_qc": route("codex", "gpt-5.6-sol", "high", 0.10, 900, 1, "anthropic_api", "claude-sonnet-5"),
}


PROMPT_PACKS: dict[str, dict[str, Any]] = {
    "aviation_investigation": {
        "id": "aviation_investigation", "label": "Aviation Investigation",
        "description": "Technically credible air-crash and disappearance investigations.",
        "instructions": "Use restrained aviation-investigation language. Distinguish recorded evidence, official findings, expert inference and unresolved theory. Preserve aircraft, cockpit, geography and timeline continuity. Never sensationalize victims.",
    },
    "engineering_failure": {
        "id": "engineering_failure", "label": "Engineering Failure",
        "description": "Bridge, building, industrial and infrastructure failures.",
        "instructions": "Explain the failure chain from load, material, process and organizational decisions. Prefer causal diagrams and evidence over spectacle. Separate initiating event from contributing conditions.",
    },
    "cyber_incident": {
        "id": "cyber_incident", "label": "Cyber Incident",
        "description": "Major breaches, outages and software-system failures.",
        "instructions": "Make digital systems understandable without inventing interfaces. Separate confirmed indicators, attributed behavior and speculation. Avoid operational instructions that could enable abuse.",
    },
    "space_mission": {
        "id": "space_mission", "label": "Space Mission Failure",
        "description": "Launch, spacecraft and mission investigations.",
        "instructions": "Maintain mission chronology, vehicle configuration and orbital realism. Explain engineering tradeoffs clearly and avoid fictional telemetry or unsupported causal certainty.",
    },
    "general_documentary": {
        "id": "general_documentary", "label": "General Investigation",
        "description": "Neutral default for any major failure or mystery.",
        "instructions": "Build curiosity through evidence and unanswered questions, not exaggeration. Clearly label uncertainty and preserve human dignity throughout the story.",
    },
}


def _profile_routes(overrides: dict[str, tuple[str, str, str]] | None = None) -> dict[str, dict[str, Any]]:
    result = copy.deepcopy(DEFAULT_TASK_ROUTES)
    for task_id, values in (overrides or {}).items():
        provider, model, reasoning = values
        result[task_id]["provider"] = provider
        result[task_id]["model"] = model
        result[task_id]["reasoning_effort"] = reasoning
    return result


PROFILES: dict[str, dict[str, Any]] = {
    "highest_quality": {
        "id": "highest_quality", "label": "Highest Quality",
        "description": "Strong reasoning, native Grok media generation, and HyperFrames rendering.",
        "routes": _profile_routes(),
    },
    "balanced": {
        "id": "balanced", "label": "Balanced",
        "description": "One subscription-backed CLI path for text and Grok media with local deterministic assembly.",
        "routes": _profile_routes({
            "structure": ("codex", "gpt-5.6-sol", "high"), "script": ("codex", "gpt-5.6-sol", "high"),
            "shot_planner": ("codex", "gpt-5.6-terra", "medium"),
            "image_prompt_writer": ("codex", "gpt-5.6-terra", "medium"),
        }),
    },
    "grok_first": {
        "id": "grok_first", "label": "Grok First",
        "description": "Use Grok CLI for every supported reasoning and media task; HyperFrames renders locally.",
        "routes": _profile_routes({
            task["id"]: ("grok_cli", "authenticated-default", "high" if task["capability"] == "structured" else "standard")
            for task in TASK_DEFINITIONS if task["capability"] in {"structured", "image", "video"}
        }),
    },
    "subscription_ui": {
        "id": "subscription_ui", "label": "Subscription UI",
        "description": "Keep image and video creation in ChatGPT/Grok UI while routing reasoning through Codex.",
        "routes": _profile_routes({
            "image_generator": ("chatgpt_ui", "ChatGPT Images", "standard"),
            "video_generator": ("grok_ui", "Grok Imagine", "standard"),
        }),
    },
    "fast": {
        "id": "fast", "label": "Fast",
        "description": "Lower reasoning with Grok CLI media and FFmpeg rendering.",
        "routes": _profile_routes({
            **{task["id"]: ("codex", "gpt-5.6-terra", "low") for task in TASK_DEFINITIONS if task["capability"] == "structured"},
            "composition_renderer": ("ffmpeg", "FFmpeg concat", "standard"),
        }),
    },
    "offline": {
        "id": "offline", "label": "Offline Test",
        "description": "No external calls; validates the complete application flow.",
        "routes": {task["id"]: route("mock", "Deterministic Demo", "low", 0, 60, 0, "mock", "Deterministic Demo") for task in TASK_DEFINITIONS},
    },
}


DEFAULT_RULES: list[dict[str, Any]] = [
    {
        "id": "long_script_quality", "label": "Long documentary script", "enabled": True,
        "task_id": "script", "field": "duration_seconds", "operator": ">", "value": 600,
        "provider": "claude_code", "model": "claude-opus-4-8", "reasoning_effort": "high",
    }
]


def default_orchestrator_config() -> dict[str, Any]:
    return {
        "version": 2,
        "active_profile": "highest_quality",
        "active_prompt_pack": "aviation_investigation",
        "tasks": copy.deepcopy(DEFAULT_TASK_ROUTES),
        "providers": {
            key: {
                "command_template": value.get("command_template", ""),
                "media_command_template": value.get("media_command_template", ""),
                "enabled": value["mode"] != "disabled",
            }
            for key, value in PROVIDERS.items()
        },
        "prompt_packs": copy.deepcopy(PROMPT_PACKS),
        "rules": copy.deepcopy(DEFAULT_RULES),
    }


def merge_orchestrator_config(saved: dict[str, Any] | None) -> dict[str, Any]:
    config = default_orchestrator_config()
    saved = saved or {}
    for key in ("active_profile", "active_prompt_pack", "version"):
        if key in saved:
            config[key] = saved[key]
    for task_id, values in saved.get("tasks", {}).items():
        if task_id in config["tasks"] and isinstance(values, dict):
            config["tasks"][task_id].update(values)
    for provider_id, values in saved.get("providers", {}).items():
        if provider_id in config["providers"] and isinstance(values, dict):
            config["providers"][provider_id].update(values)
    for pack_id, values in saved.get("prompt_packs", {}).items():
        if pack_id in config["prompt_packs"] and isinstance(values, dict):
            config["prompt_packs"][pack_id].update(values)
    if isinstance(saved.get("rules"), list):
        config["rules"] = saved["rules"]
    return config


def apply_profile(config: dict[str, Any], profile_id: str) -> dict[str, Any]:
    if profile_id not in PROFILES:
        raise ValueError(f"Unknown profile: {profile_id}")
    result = merge_orchestrator_config(config)
    result["active_profile"] = profile_id
    result["tasks"] = copy.deepcopy(PROFILES[profile_id]["routes"])
    return result


def provider_health(provider_id: str, provider_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    if provider_id not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider_id}")
    provider = PROVIDERS[provider_id]
    overrides = provider_overrides or {}
    enabled = bool(overrides.get("enabled", provider["mode"] != "disabled"))
    if not enabled:
        return {"provider_id": provider_id, "status": "disabled", "healthy": False, "detail": "Provider is disabled"}
    if provider["mode"] == "manual":
        return {"provider_id": provider_id, "status": "ready", "healthy": True, "detail": "Manual handoff ready"}
    if provider["mode"] == "mock":
        return {"provider_id": provider_id, "status": "ready", "healthy": True, "detail": "Offline generator ready"}
    if provider_id == "anthropic_api":
        configured = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
        return {
            "provider_id": provider_id,
            "status": "ready" if configured else "unconfigured",
            "healthy": configured,
            "detail": "ANTHROPIC_API_KEY configured" if configured else "Set ANTHROPIC_API_KEY before starting Studio",
        }
    if provider_id == "custom_cli":
        configured = bool((overrides.get("command_template") or "").strip() or (overrides.get("media_command_template") or "").strip())
        return {"provider_id": provider_id, "status": "ready" if configured else "unconfigured", "healthy": configured, "detail": "Custom command configured" if configured else "Add a structured or media command template"}
    if provider_id == "hyperframes":
        root = Path(__file__).resolve().parents[1]
        local = root / "node_modules/.bin/hyperframes"
        found = bool(shutil.which("hyperframes") or local.exists() or shutil.which("npx"))
        return {"provider_id": provider_id, "status": "ready" if found else "missing", "healthy": found, "detail": "HyperFrames runtime available" if found else "Run npm install in the repository"}
    executable = provider.get("executable")
    found = bool(executable and shutil.which(executable))
    return {
        "provider_id": provider_id, "status": "ready" if found else "missing", "healthy": found,
        "detail": f"{executable} found on PATH" if found else f"Install or expose the {executable} executable",
    }


def resolve_task(config: dict[str, Any], task_id: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    if task_id not in config.get("tasks", {}):
        raise ValueError(f"Unknown orchestration task: {task_id}")
    definitions = {item["id"]: item for item in TASK_DEFINITIONS}
    definition = definitions[task_id]
    resolved = copy.deepcopy(config["tasks"][task_id])
    context = context or {}
    for rule in config.get("rules", []):
        if not rule.get("enabled") or rule.get("task_id") != task_id:
            continue
        actual = context.get(rule.get("field"))
        if _matches(actual, rule.get("operator"), rule.get("value")):
            for key in ("provider", "model", "reasoning_effort", "temperature", "timeout_seconds", "retry_count"):
                if key in rule:
                    resolved[key] = rule[key]
            resolved["matched_rule"] = rule.get("label") or rule.get("id")
            break
    provider_id = resolved.get("provider", "mock")
    provider = PROVIDERS.get(provider_id, PROVIDERS["mock"])
    required_capability = definition["capability"]
    if required_capability not in provider.get("capabilities", []):
        raise ValueError(f"Provider {provider_id} cannot execute {required_capability} task {task_id}")
    provider_override = config.get("providers", {}).get(provider_id, {})
    resolved.update({
        "task_id": task_id,
        "capability": required_capability,
        "provider_mode": provider["mode"],
        "provider_adapter": provider.get("adapter", provider["mode"]),
        "provider_label": provider["label"],
        "command_template": provider_override.get("command_template") or provider.get("command_template", ""),
        "media_command_template": provider_override.get("media_command_template") or provider.get("media_command_template", ""),
    })
    fallback_id = resolved.get("fallback_provider")
    fallback = PROVIDERS.get(fallback_id, {})
    if fallback_id and required_capability not in fallback.get("capabilities", []):
        raise ValueError(f"Fallback provider {fallback_id} cannot execute {required_capability} task {task_id}")
    fallback_override = config.get("providers", {}).get(fallback_id, {})
    resolved["fallback_provider_mode"] = fallback.get("mode", "disabled")
    resolved["fallback_provider_adapter"] = fallback.get("adapter", fallback.get("mode", "disabled"))
    resolved["fallback_provider_label"] = fallback.get("label", fallback_id or "No fallback")
    resolved["fallback_command_template"] = fallback_override.get("command_template") or fallback.get("command_template", "")
    resolved["fallback_media_command_template"] = fallback_override.get("media_command_template") or fallback.get("media_command_template", "")
    pack_id = config.get("active_prompt_pack", "general_documentary")
    pack = config.get("prompt_packs", {}).get(pack_id, PROMPT_PACKS["general_documentary"])
    resolved["prompt_pack_id"] = pack_id
    resolved["prompt_pack_label"] = pack.get("label", pack_id)
    resolved["prompt_pack_instructions"] = pack.get("instructions", "")
    return resolved


def public_payload(config: dict[str, Any]) -> dict[str, Any]:
    health = {provider_id: provider_health(provider_id, config.get("providers", {}).get(provider_id)) for provider_id in PROVIDERS}
    definitions = {item["id"]: item for item in TASK_DEFINITIONS}
    tasks = []
    for task_id, route_config in config.get("tasks", {}).items():
        item = copy.deepcopy(definitions[task_id])
        item.update(copy.deepcopy(route_config))
        provider = PROVIDERS.get(item.get("provider"), PROVIDERS["mock"])
        item["provider_label"] = provider["label"]
        item["provider_mode"] = provider["mode"]
        item["provider_capabilities"] = provider.get("capabilities", [])
        item["health"] = health.get(item.get("provider"), {})
        tasks.append(item)
    return {
        **copy.deepcopy(config),
        "tasks": tasks,
        "provider_catalog": [copy.deepcopy(value) | {"health": health[key]} for key, value in PROVIDERS.items()],
        "profiles": [copy.deepcopy(value) | {"task_count": len(value["routes"])} for value in PROFILES.values()],
        "task_definitions": copy.deepcopy(TASK_DEFINITIONS),
    }


def _matches(actual: Any, operator: str | None, expected: Any) -> bool:
    try:
        if operator == ">": return float(actual) > float(expected)
        if operator == ">=": return float(actual) >= float(expected)
        if operator == "<": return float(actual) < float(expected)
        if operator == "<=": return float(actual) <= float(expected)
        if operator == "contains": return str(expected).lower() in str(actual).lower()
        if operator == "==": return str(actual) == str(expected)
    except (TypeError, ValueError):
        return False
    return False
