from __future__ import annotations

import copy
import importlib.util
import os
import shutil
from pathlib import Path
from typing import Any

DOCS_CHECKED_AT = "2026-07-23"


def _provider(
    provider_id: str,
    label: str,
    *,
    mode: str,
    adapter: str,
    capabilities: list[str],
    models_by_capability: dict[str, list[str]],
    description: str,
    docs_url: str,
    executable: str | None = None,
    command_template: str = "",
    media_command_template: str = "",
    options: dict[str, Any] | None = None,
    integration_notes: str = "",
) -> dict[str, Any]:
    return {
        "id": provider_id,
        "label": label,
        "mode": mode,
        "adapter": adapter,
        "executable": executable,
        "description": description,
        "capabilities": capabilities,
        "models_by_capability": models_by_capability,
        "models": list(dict.fromkeys(model for values in models_by_capability.values() for model in values)),
        "command_template": command_template,
        "media_command_template": media_command_template,
        "options": options or {},
        "docs_url": docs_url,
        "docs_checked_at": DOCS_CHECKED_AT,
        "integration_notes": integration_notes,
    }


PROVIDERS: dict[str, dict[str, Any]] = {
    "codex": _provider(
        "codex", "Codex CLI (ChatGPT)", mode="command", adapter="command",
        executable="codex", capabilities=["structured"],
        models_by_capability={"structured": ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"]},
        description="ChatGPT-authenticated Codex CLI for evidence synthesis, writing, and visual direction.",
        docs_url="https://developers.openai.com/api/docs/models",
        command_template="codex exec --skip-git-repo-check --model {model} --output-last-message {output} - < {prompt}",
        options={"reasoning_effort": ["none", "low", "medium", "high", "xhigh", "max"]},
    ),
    "anthropic_api": _provider(
        "anthropic_api", "Claude API", mode="api", adapter="anthropic_api",
        capabilities=["structured"],
        models_by_capability={"structured": [
            "claude-fable-5", "claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5",
        ]},
        description="Anthropic Messages API with contract-constrained JSON output.",
        docs_url="https://platform.claude.com/docs/en/about-claude/models/overview",
        options={"reasoning_effort": ["low", "medium", "high", "max"]},
    ),
    "grok_cli": _provider(
        "grok_cli", "Grok Build CLI", mode="native_cli", adapter="grok_cli",
        executable="grok", capabilities=["structured", "image", "video"],
        models_by_capability={
            "structured": ["authenticated-default", "grok-4.5", "grok-4.3", "grok-build-0.1"],
            "image": ["grok-imagine-image-quality", "grok-imagine-image"],
            "video": ["grok-imagine-video-1.5", "grok-imagine-video"],
        },
        description="Subscription-backed Grok CLI for structured work and built-in Imagine media tools.",
        docs_url="https://docs.x.ai/developers/models",
        options={
            "image": {
                "resolutions_by_model": {
                    "grok-imagine-image-quality": ["1K", "2K"],
                    "grok-imagine-image": ["1K", "2K"],
                },
                "quality": ["standard", "quality"],
                "aspect_ratio": ["16:9", "3:2", "4:3", "1:1", "9:16"],
            },
            "video": {
                "resolutions_by_model": {
                    "grok-imagine-video-1.5": ["480p", "720p", "1080p"],
                    "grok-imagine-video": ["480p", "720p"],
                },
                "aspect_ratio": ["16:9", "9:16"],
                "duration_seconds": [5, 6, 8, 10, 12],
            },
        },
        integration_notes=(
            "The selected Imagine model, resolution, quality, aspect ratio, and duration are placed explicitly in the "
            "Grok CLI tool brief and persisted with the result. Grok CLI may internally route its built-in Imagine tool."
        ),
    ),
    "kimi_api": _provider(
        "kimi_api", "Kimi API", mode="api", adapter="kimi_api",
        capabilities=["structured"],
        models_by_capability={"structured": [
            "kimi-k3", "kimi-k2.7-code", "kimi-k2.7-code-highspeed", "kimi-k2.6", "kimi-k2.5",
        ]},
        description="Moonshot Kimi OpenAI-compatible API with JSON mode.",
        docs_url="https://platform.kimi.ai/docs/overview",
        options={"reasoning_effort": ["low", "high", "max"]},
    ),
    "gemini_api": _provider(
        "gemini_api", "Gemini API", mode="api", adapter="gemini_api",
        capabilities=["structured", "image", "video"],
        models_by_capability={
            "structured": [
                "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite",
                "gemini-3.1-pro-preview", "gemini-3.1-flash-lite", "gemini-2.5-pro", "gemini-2.5-flash",
            ],
            "image": [
                "gemini-3.1-flash-image", "gemini-3.1-flash-lite-image",
                "gemini-3-pro-image", "gemini-2.5-flash-image",
            ],
            "video": [
                "gemini-omni-flash-preview", "veo-3.1-generate-preview",
                "veo-3.1-fast-generate-preview", "veo-3.1-lite-generate-preview",
            ],
        },
        description="Gemini API for structured reasoning, current image models, and current video models.",
        docs_url="https://ai.google.dev/gemini-api/docs/models",
        options={
            "image": {
                "resolutions_by_model": {
                    "gemini-3.1-flash-image": ["0.5K", "1K", "2K", "4K"],
                    "gemini-3.1-flash-lite-image": ["1K"],
                    "gemini-3-pro-image": ["1K", "2K", "4K"],
                    "gemini-2.5-flash-image": ["1K"],
                },
                "quality": ["standard", "high"],
                "aspect_ratio": ["16:9", "3:2", "4:3", "1:1", "9:16"],
            },
            "video": {
                "resolutions_by_model": {
                    "gemini-omni-flash-preview": ["720p"],
                    "veo-3.1-generate-preview": ["720p", "1080p", "4K"],
                    "veo-3.1-fast-generate-preview": ["720p", "1080p", "4K"],
                    "veo-3.1-lite-generate-preview": ["720p", "1080p"],
                },
                "aspect_ratio": ["16:9", "9:16"],
                "duration_by_model": {
                    "gemini-omni-flash-preview": [3, 4, 5, 6, 7, 8, 9, 10],
                    "veo-3.1-generate-preview": [4, 6, 8],
                    "veo-3.1-fast-generate-preview": [4, 6, 8],
                    "veo-3.1-lite-generate-preview": [4, 6, 8],
                },
            },
        },
    ),
    "gemini_cli": _provider(
        "gemini_cli", "Gemini CLI", mode="native_cli", adapter="gemini_cli",
        executable="gemini", capabilities=["structured"],
        models_by_capability={"structured": [
            "auto", "pro", "flash", "flash-lite", "gemini-3.1-pro-preview",
            "gemini-3-flash-preview", "gemini-3.1-flash-lite",
            "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite",
        ]},
        description="Google-authenticated Gemini CLI using its documented headless JSON envelope.",
        docs_url="https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/headless.md",
        options={"reasoning_effort": ["low", "medium", "high"]},
    ),
    "openai_image_api": _provider(
        "openai_image_api", "OpenAI GPT Image API", mode="api", adapter="openai_image_api",
        capabilities=["image"],
        models_by_capability={"image": ["gpt-image-2", "gpt-image-2-2026-04-21"]},
        description="OpenAI Images API using GPT Image 2.",
        docs_url="https://developers.openai.com/api/docs/models/gpt-image-2",
        options={
            "image": {
                "resolutions_by_model": {
                    "gpt-image-2": ["auto", "1024x1024", "1536x1024", "1024x1536"],
                    "gpt-image-2-2026-04-21": ["auto", "1024x1024", "1536x1024", "1024x1536"],
                },
                "quality": ["auto", "low", "medium", "high"],
                "aspect_ratio": ["auto", "1:1", "3:2", "2:3"],
            }
        },
        integration_notes="OpenAI exposes exact pixel sizes rather than generic 1K/2K labels; the UI therefore shows its native size values.",
    ),
    "google_tts": _provider(
        "google_tts", "Google Gemini TTS", mode="api", adapter="google_tts",
        capabilities=["audio"],
        models_by_capability={"audio": [
            "gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts", "gemini-2.5-pro-preview-tts",
        ]},
        description="Gemini speech generation with steerable documentary delivery.",
        docs_url="https://ai.google.dev/gemini-api/docs/speech-generation",
        options={"audio": {
            "quality": ["fast", "balanced", "high_fidelity"],
            "voices": ["Kore", "Charon", "Fenrir", "Aoede", "Puck", "Leda", "Orus", "Zephyr"],
        }},
    ),
    "whisper_local": _provider(
        "whisper_local", "Local Whisper Alignment", mode="local", adapter="whisper_local",
        capabilities=["alignment"],
        models_by_capability={"alignment": ["tiny.en", "base.en", "small.en", "medium.en", "large-v3"]},
        description="Local word alignment tied to the approved voiceover hash.",
        docs_url="https://github.com/openai/whisper",
    ),
    "ffmpeg": _provider(
        "ffmpeg", "FFmpeg Renderer", mode="local", adapter="ffmpeg",
        executable="ffmpeg", capabilities=["render"],
        models_by_capability={"render": ["FFmpeg deterministic"]},
        description="Local animatic and final-preview rendering.",
        docs_url="https://ffmpeg.org/documentation.html",
        options={"render": {"resolutions": ["720p", "1080p", "1440p", "4K"]}},
    ),
    "hyperframes": _provider(
        "hyperframes", "HyperFrames", mode="local", adapter="hyperframes",
        executable="hyperframes", capabilities=["render"],
        models_by_capability={"render": ["HyperFrames 0.7.62"]},
        description="Frame-accurate browser composition and rendering.",
        docs_url="https://github.com/hyperframes/hyperframes",
    ),
    "manual_upload": _provider(
        "manual_upload", "Manual Upload", mode="manual", adapter="manual",
        capabilities=["image", "video", "audio"],
        models_by_capability={
            "image": ["External image tool"], "video": ["External video tool"], "audio": ["External narration"],
        },
        description="Import externally generated or recorded media while preserving the stage contract.",
        docs_url="https://github.com/ananthcjayan12/failure-documentary-engine",
    ),
    "custom_cli": _provider(
        "custom_cli", "Custom CLI Adapter", mode="command", adapter="custom_cli",
        capabilities=["structured", "image", "video", "audio"],
        models_by_capability={
            "structured": ["custom-model"], "image": ["custom-image-model"],
            "video": ["custom-video-model"], "audio": ["custom-audio-model"],
        },
        description="Advanced command-template adapter for another private provider.",
        docs_url="https://github.com/ananthcjayan12/failure-documentary-engine",
    ),
    "mock": _provider(
        "mock", "Offline Mock", mode="mock", adapter="mock",
        capabilities=["structured", "image", "video", "audio", "alignment", "render"],
        models_by_capability={capability: ["Deterministic Demo"] for capability in [
            "structured", "image", "video", "audio", "alignment", "render",
        ]},
        description="Deterministic offline provider for pipeline and UI tests.",
        docs_url="https://github.com/ananthcjayan12/failure-documentary-engine",
    ),
}


# These are the tasks that are actually executed by the current V1 pipeline. The router intentionally
# does not display fictional QA or prompt-writing tasks that have no executable stage behind them.
TASK_DEFINITIONS: list[dict[str, Any]] = [
    {"id": "research", "label": "Research dossier", "stage": 1, "pipeline_stage": "story_setup", "group": "Story setup", "capability": "structured", "description": "Build the source dossier, chronology, evidence list, and claim ledger."},
    {"id": "structure", "label": "Story structure", "stage": 1, "pipeline_stage": "story_setup", "group": "Story setup", "capability": "structured", "description": "Design chapters, escalation, reveals, and the ending."},
    {"id": "narration_writer", "label": "Narration writer", "stage": 2, "pipeline_stage": "narration", "group": "Narration", "capability": "structured", "description": "Write evidence-grounded spoken narration with sparse performance tags."},
    {"id": "voice_generator", "label": "Documentary voice", "stage": 3, "pipeline_stage": "voice", "group": "Voice and timing", "capability": "audio", "description": "Generate chapter-cached narration and assemble the voice master."},
    {"id": "word_alignment", "label": "Word alignment", "stage": 3, "pipeline_stage": "voice", "group": "Voice and timing", "capability": "alignment", "description": "Create word timestamps tied to the current voiceover hash."},
    {"id": "shot_planner", "label": "Audio-led visual director", "stage": 4, "pipeline_stage": "shots", "group": "Shots", "capability": "structured", "description": "Design visual treatments and prompts around deterministic word/pause boundaries."},
    {"id": "image_generator", "label": "Image generator", "stage": 5, "pipeline_stage": "images", "group": "Images", "capability": "image", "description": "Generate one primary still for each approved shot using the selected model and quality."},
    {"id": "animatic_renderer", "label": "Animatic renderer", "stage": 6, "pipeline_stage": "animatic", "group": "Image + sound preview", "capability": "render", "description": "Combine approved images, exact narration, and restrained ambience."},
    {"id": "video_generator", "label": "Video generator", "stage": 7, "pipeline_stage": "videos", "group": "Videos", "capability": "video", "description": "Generate selected clips with explicit model, resolution, duration, and aspect ratio."},
    {"id": "final_renderer", "label": "Final preview renderer", "stage": 8, "pipeline_stage": "final_preview", "group": "Final preview", "capability": "render", "description": "Assemble approved videos, image fallbacks, and master narration."},
]
TASK_BY_ID = {item["id"]: item for item in TASK_DEFINITIONS}
TASK_ALIASES = {
    "script": "narration_writer",
    "script_qa": "narration_writer",
    "narration_qa": "narration_writer",
    "fact_verification": "research",
    "timeline_builder": "shot_planner",
    "image_prompt_writer": "shot_planner",
    "animation_prompt_writer": "shot_planner",
    "video_prompt_writer": "shot_planner",
    "shot_qa": "shot_planner",
    "image_qc": "image_generator",
    "video_qc": "video_generator",
    "composition_renderer": "final_renderer",
    "final_qc": "final_renderer",
    "asset_optimizer": "shot_planner",
}


def route(
    provider: str,
    model: str,
    reasoning: str,
    temperature: float,
    timeout: int,
    retries: int,
    fallback_provider: str,
    fallback_model: str,
    *,
    quality: str = "",
    resolution: str = "",
    aspect_ratio: str = "",
    duration_seconds: int | float = 0,
    voice: str = "",
) -> dict[str, Any]:
    return {
        "provider": provider, "model": model, "reasoning_effort": reasoning,
        "temperature": temperature, "timeout_seconds": timeout, "retry_count": retries,
        "fallback_provider": fallback_provider, "fallback_model": fallback_model,
        "quality": quality, "resolution": resolution, "aspect_ratio": aspect_ratio,
        "duration_seconds": duration_seconds, "voice": voice, "enabled": True,
    }


DEFAULT_TASK_ROUTES: dict[str, dict[str, Any]] = {
    "research": route("codex", "gpt-5.6-sol", "high", 0.2, 1500, 1, "anthropic_api", "claude-sonnet-5"),
    "structure": route("anthropic_api", "claude-opus-4-8", "high", 0.35, 1500, 1, "codex", "gpt-5.6-sol"),
    "narration_writer": route("anthropic_api", "claude-sonnet-5", "high", 0.45, 1800, 1, "codex", "gpt-5.6-sol"),
    "voice_generator": route("google_tts", "gemini-3.1-flash-tts-preview", "standard", 0, 1800, 1, "manual_upload", "External narration", quality="balanced", voice="Kore"),
    "word_alignment": route("whisper_local", "base.en", "standard", 0, 3600, 0, "mock", "Deterministic Demo"),
    "shot_planner": route("gemini_api", "gemini-3.1-pro-preview", "high", 0.25, 1500, 1, "anthropic_api", "claude-sonnet-5"),
    "image_generator": route("grok_cli", "grok-imagine-image-quality", "standard", 0, 3600, 1, "gemini_api", "gemini-3.1-flash-image", quality="quality", resolution="2K", aspect_ratio="16:9"),
    "animatic_renderer": route("ffmpeg", "FFmpeg deterministic", "standard", 0, 14400, 1, "hyperframes", "HyperFrames 0.7.62", resolution="720p", aspect_ratio="16:9"),
    "video_generator": route("grok_cli", "grok-imagine-video-1.5", "standard", 0, 7200, 1, "gemini_api", "veo-3.1-fast-generate-preview", quality="standard", resolution="720p", aspect_ratio="16:9", duration_seconds=8),
    "final_renderer": route("ffmpeg", "FFmpeg deterministic", "standard", 0, 14400, 1, "hyperframes", "HyperFrames 0.7.62", resolution="1080p", aspect_ratio="16:9"),
}


PROMPT_PACKS: dict[str, dict[str, Any]] = {
    "aviation_investigation": {"id": "aviation_investigation", "label": "Aviation Investigation", "description": "Technically credible air-crash and disappearance investigations.", "instructions": "Use restrained aviation-investigation language. Distinguish recorded evidence, official findings, expert inference and unresolved theory. Preserve aircraft, cockpit, geography and timeline continuity. Never sensationalize victims."},
    "engineering_failure": {"id": "engineering_failure", "label": "Engineering Failure", "description": "Bridge, building, industrial and infrastructure failures.", "instructions": "Explain the failure chain from load, material, process and organizational decisions. Prefer evidence over spectacle. Separate the initiating event from contributing conditions."},
    "cyber_incident": {"id": "cyber_incident", "label": "Cyber Incident", "description": "Major breaches, outages and software-system failures.", "instructions": "Make digital systems understandable without inventing interfaces. Separate confirmed indicators, attributed behavior and speculation."},
    "space_mission": {"id": "space_mission", "label": "Space Mission Failure", "description": "Launch, spacecraft and mission investigations.", "instructions": "Maintain mission chronology, vehicle configuration and orbital realism. Explain tradeoffs clearly and avoid fictional telemetry."},
    "general_documentary": {"id": "general_documentary", "label": "General Investigation", "description": "Neutral default for any major failure or mystery.", "instructions": "Build curiosity through evidence and unanswered questions, not exaggeration. Clearly label uncertainty and preserve human dignity."},
}


def _profile_routes(overrides: dict[str, tuple[str, str, str]] | None = None) -> dict[str, dict[str, Any]]:
    result = copy.deepcopy(DEFAULT_TASK_ROUTES)
    for task_id, (provider, model, reasoning) in (overrides or {}).items():
        if task_id in result:
            result[task_id].update({"provider": provider, "model": model, "reasoning_effort": reasoning})
    return result


PROFILES: dict[str, dict[str, Any]] = {
    "highest_quality": {"id": "highest_quality", "label": "Highest Quality", "description": "Claude and GPT-5.6 for the spoken story, Gemini Pro visual direction, 2K Grok images, and 720p Grok video.", "routes": _profile_routes()},
    "balanced": {"id": "balanced", "label": "Balanced", "description": "GPT-5.6 Terra and Gemini Flash for structured work, standard 1K images, and 720p video.", "routes": _profile_routes({
        "research": ("codex", "gpt-5.6-terra", "medium"),
        "structure": ("gemini_api", "gemini-3.5-flash", "high"),
        "narration_writer": ("codex", "gpt-5.6-terra", "high"),
        "shot_planner": ("gemini_api", "gemini-3.5-flash", "high"),
    })},
    "api_first": {"id": "api_first", "label": "API First", "description": "Claude, Kimi, and Gemini APIs with Gemini image/video generation.", "routes": _profile_routes({
        "research": ("kimi_api", "kimi-k3", "high"),
        "structure": ("anthropic_api", "claude-opus-4-8", "high"),
        "narration_writer": ("anthropic_api", "claude-sonnet-5", "high"),
        "shot_planner": ("gemini_api", "gemini-3.1-pro-preview", "high"),
        "image_generator": ("gemini_api", "gemini-3.1-flash-image", "standard"),
        "video_generator": ("gemini_api", "veo-3.1-fast-generate-preview", "standard"),
    })},
    "subscription_cli": {"id": "subscription_cli", "label": "Subscription CLI", "description": "Codex, Gemini CLI, and Grok CLI minimize structured API calls.", "routes": _profile_routes({
        "research": ("codex", "gpt-5.6-terra", "medium"),
        "structure": ("gemini_cli", "pro", "high"),
        "narration_writer": ("codex", "gpt-5.6-sol", "high"),
        "shot_planner": ("gemini_cli", "pro", "high"),
    })},
    "fast_low_cost": {"id": "fast_low_cost", "label": "Fast / Low Cost", "description": "Kimi K2.7 high-speed, Gemini Flash-Lite, 1K images, and 480p video.", "routes": _profile_routes({
        "research": ("kimi_api", "kimi-k2.7-code-highspeed", "low"),
        "structure": ("gemini_api", "gemini-3.5-flash-lite", "low"),
        "narration_writer": ("kimi_api", "kimi-k3", "high"),
        "shot_planner": ("gemini_api", "gemini-3.5-flash-lite", "low"),
        "image_generator": ("grok_cli", "grok-imagine-image", "standard"),
        "video_generator": ("grok_cli", "grok-imagine-video", "standard"),
    })},
    "offline": {"id": "offline", "label": "Offline Test", "description": "No external calls; validates restarts, routing, media, and rendering.", "routes": {
        task["id"]: route("mock", "Deterministic Demo", "low", 0, 120, 0, "mock", "Deterministic Demo")
        for task in TASK_DEFINITIONS
    }},
}
PROFILES["balanced"]["routes"]["image_generator"].update({"resolution": "1K", "quality": "standard"})
PROFILES["api_first"]["routes"]["image_generator"].update({"resolution": "2K", "quality": "high", "aspect_ratio": "16:9"})
PROFILES["api_first"]["routes"]["video_generator"].update({"resolution": "720p", "aspect_ratio": "16:9", "duration_seconds": 8})
PROFILES["fast_low_cost"]["routes"]["image_generator"].update({"resolution": "1K", "quality": "standard"})
PROFILES["fast_low_cost"]["routes"]["video_generator"].update({"resolution": "480p", "duration_seconds": 5})

DEFAULT_RULES = [{
    "id": "long_narration_quality", "label": "Long documentary narration", "enabled": True,
    "task_id": "narration_writer", "field": "duration_seconds", "operator": ">", "value": 600,
    "provider": "anthropic_api", "model": "claude-fable-5", "reasoning_effort": "high",
}]


def default_orchestrator_config() -> dict[str, Any]:
    return {
        "version": 4,
        "active_profile": "highest_quality",
        "active_prompt_pack": "aviation_investigation",
        "tasks": copy.deepcopy(DEFAULT_TASK_ROUTES),
        "providers": {key: {
            "command_template": value.get("command_template", ""),
            "media_command_template": value.get("media_command_template", ""),
            "enabled": True,
        } for key, value in PROVIDERS.items()},
        "prompt_packs": copy.deepcopy(PROMPT_PACKS),
        "rules": copy.deepcopy(DEFAULT_RULES),
    }


def merge_orchestrator_config(saved: dict[str, Any] | None) -> dict[str, Any]:
    config = default_orchestrator_config()
    saved = saved or {}
    for key in ("active_profile", "active_prompt_pack"):
        if key in saved:
            config[key] = saved[key]
    for raw_task_id, values in (saved.get("tasks", {}) if isinstance(saved.get("tasks"), dict) else {}).items():
        task_id = TASK_ALIASES.get(raw_task_id, raw_task_id)
        if task_id in config["tasks"] and isinstance(values, dict):
            config["tasks"][task_id].update(values)
    for provider_id, values in saved.get("providers", {}).items():
        if provider_id in config["providers"] and isinstance(values, dict):
            config["providers"][provider_id].update(values)
    for pack_id, values in saved.get("prompt_packs", {}).items():
        if pack_id in config["prompt_packs"] and isinstance(values, dict):
            config["prompt_packs"][pack_id].update(values)
    if isinstance(saved.get("rules"), list):
        config["rules"] = [{**item, "task_id": TASK_ALIASES.get(item.get("task_id"), item.get("task_id"))} for item in saved["rules"] if isinstance(item, dict)]
    config["version"] = 4
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
    if not bool(overrides.get("enabled", True)):
        return {"provider_id": provider_id, "status": "disabled", "healthy": False, "detail": "Provider is disabled"}
    if provider["mode"] in {"manual", "mock"}:
        return {"provider_id": provider_id, "status": "ready", "healthy": True, "detail": "Provider is ready"}
    key_map = {
        "anthropic_api": ("ANTHROPIC_API_KEY",),
        "kimi_api": ("MOONSHOT_API_KEY",),
        "gemini_api": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "google_tts": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "openai_image_api": ("OPENAI_API_KEY",),
    }
    if provider_id in key_map:
        names = key_map[provider_id]
        configured = any(os.environ.get(name, "").strip() for name in names)
        return {
            "provider_id": provider_id, "status": "ready" if configured else "unconfigured",
            "healthy": configured,
            "detail": f"{names[0]} configured" if configured else f"Set {' or '.join(names)} before starting Studio",
        }
    if provider_id == "whisper_local":
        found = importlib.util.find_spec("whisper") is not None
        return {
            "provider_id": provider_id, "status": "ready" if found else "missing", "healthy": found,
            "detail": "openai-whisper installed" if found else "Install: pip install -e '.[alignment]'",
        }
    if provider_id == "custom_cli":
        configured = bool((overrides.get("command_template") or "").strip() or (overrides.get("media_command_template") or "").strip())
        return {"provider_id": provider_id, "status": "ready" if configured else "unconfigured", "healthy": configured, "detail": "Custom command configured" if configured else "Add a command template"}
    if provider_id == "hyperframes":
        root = Path(__file__).resolve().parents[1]
        found = bool(shutil.which("hyperframes") or (root / "node_modules/.bin/hyperframes").exists() or shutil.which("npx"))
        return {"provider_id": provider_id, "status": "ready" if found else "missing", "healthy": found, "detail": "HyperFrames available" if found else "Run npm install"}
    executable = provider.get("executable")
    found = bool(executable and shutil.which(executable))
    return {
        "provider_id": provider_id, "status": "ready" if found else "missing", "healthy": found,
        "detail": f"{executable} found on PATH" if found else f"Install or expose {executable}",
    }


def _models_for(provider: dict[str, Any], capability: str) -> list[str]:
    return list(provider.get("models_by_capability", {}).get(capability, []))


def _validate_media_settings(provider: dict[str, Any], capability: str, route_config: dict[str, Any]) -> None:
    if capability not in {"image", "video", "render"}:
        return
    options = provider.get("options", {}).get(capability, {})
    model = route_config.get("model", "")
    resolutions = options.get("resolutions_by_model", {}).get(model, options.get("resolutions", []))
    resolution = route_config.get("resolution", "")
    if resolution and resolutions and resolution not in resolutions:
        raise ValueError(f"Resolution {resolution} is not supported by {provider['label']} model {model}")
    ratios = options.get("aspect_ratio", [])
    ratio = route_config.get("aspect_ratio", "")
    if ratio and ratios and ratio not in ratios:
        raise ValueError(f"Aspect ratio {ratio} is not supported by {provider['label']}")
    durations = options.get("duration_by_model", {}).get(model, options.get("duration_seconds", []))
    duration = route_config.get("duration_seconds", 0)
    if duration and durations and float(duration) not in {float(value) for value in durations}:
        raise ValueError(f"Duration {duration}s is not supported by {provider['label']} model {model}")


def resolve_task(config: dict[str, Any], task_id: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    task_id = TASK_ALIASES.get(task_id, task_id)
    if task_id not in config.get("tasks", {}):
        raise ValueError(f"Unknown orchestration task: {task_id}")
    definition = TASK_BY_ID[task_id]
    resolved = copy.deepcopy(config["tasks"][task_id])
    context = context or {}
    for rule in config.get("rules", []):
        if not isinstance(rule, dict) or not rule.get("enabled") or TASK_ALIASES.get(rule.get("task_id"), rule.get("task_id")) != task_id:
            continue
        if _matches(context.get(rule.get("field")), rule.get("operator"), rule.get("value")):
            for key in ("provider", "model", "reasoning_effort", "temperature", "timeout_seconds", "retry_count", "quality", "resolution", "aspect_ratio", "duration_seconds", "voice"):
                if key in rule:
                    resolved[key] = rule[key]
            resolved["matched_rule"] = rule.get("label") or rule.get("id")
            break
    provider_id = resolved.get("provider", "mock")
    if provider_id not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider_id}")
    provider = PROVIDERS[provider_id]
    capability = definition["capability"]
    if capability not in provider.get("capabilities", []):
        raise ValueError(f"Provider {provider_id} cannot execute {capability} task {task_id}")
    models = _models_for(provider, capability)
    if models and resolved.get("model", "") not in models and provider_id != "custom_cli":
        raise ValueError(f"Model {resolved.get('model')} is not a verified {capability} model for {provider['label']}")
    _validate_media_settings(provider, capability, resolved)
    provider_override = config.get("providers", {}).get(provider_id, {})
    resolved.update({
        "task_id": task_id, "pipeline_stage": definition["pipeline_stage"], "capability": capability,
        "provider_mode": provider["mode"], "provider_adapter": provider["adapter"],
        "provider_label": provider["label"], "provider_docs_url": provider["docs_url"],
        "provider_docs_checked_at": provider["docs_checked_at"],
        "command_template": provider_override.get("command_template") or provider.get("command_template", ""),
        "media_command_template": provider_override.get("media_command_template") or provider.get("media_command_template", ""),
    })
    fallback_id = resolved.get("fallback_provider")
    fallback = PROVIDERS.get(fallback_id, {})
    if fallback_id and capability not in fallback.get("capabilities", []):
        raise ValueError(f"Fallback provider {fallback_id} cannot execute {capability} task {task_id}")
    if fallback_id:
        fallback_models = _models_for(fallback, capability)
        if fallback_models and resolved.get("fallback_model", "") not in fallback_models and fallback_id != "custom_cli":
            raise ValueError(f"Fallback model {resolved.get('fallback_model')} is not verified for {fallback.get('label', fallback_id)}")
    fallback_override = config.get("providers", {}).get(fallback_id, {})
    resolved.update({
        "fallback_provider_mode": fallback.get("mode", "disabled"),
        "fallback_provider_adapter": fallback.get("adapter", fallback.get("mode", "disabled")),
        "fallback_provider_label": fallback.get("label", fallback_id or "No fallback"),
        "fallback_command_template": fallback_override.get("command_template") or fallback.get("command_template", ""),
        "fallback_media_command_template": fallback_override.get("media_command_template") or fallback.get("media_command_template", ""),
    })
    pack_id = config.get("active_prompt_pack", "general_documentary")
    pack = config.get("prompt_packs", {}).get(pack_id, PROMPT_PACKS["general_documentary"])
    resolved.update({
        "prompt_pack_id": pack_id, "prompt_pack_label": pack.get("label", pack_id),
        "prompt_pack_instructions": pack.get("instructions", ""),
    })
    return resolved


def public_payload(config: dict[str, Any]) -> dict[str, Any]:
    health = {provider_id: provider_health(provider_id, config.get("providers", {}).get(provider_id)) for provider_id in PROVIDERS}
    tasks = []
    for definition in TASK_DEFINITIONS:
        route_config = config.get("tasks", {}).get(definition["id"], DEFAULT_TASK_ROUTES[definition["id"]])
        item = copy.deepcopy(definition)
        item.update(copy.deepcopy(route_config))
        provider = PROVIDERS.get(item.get("provider"), PROVIDERS["mock"])
        item.update({
            "provider_label": provider["label"], "provider_mode": provider["mode"],
            "provider_capabilities": provider["capabilities"], "health": health.get(item.get("provider"), {}),
        })
        tasks.append(item)
    return {
        **copy.deepcopy(config), "tasks": tasks,
        "provider_catalog": [copy.deepcopy(value) | {"health": health[key]} for key, value in PROVIDERS.items()],
        "profiles": [copy.deepcopy(value) | {"task_count": len(value["routes"])} for value in PROFILES.values()],
        "task_definitions": copy.deepcopy(TASK_DEFINITIONS), "docs_checked_at": DOCS_CHECKED_AT,
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
