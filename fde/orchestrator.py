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
    models = list(dict.fromkeys(model for values in models_by_capability.values() for model in values))
    return {
        "id": provider_id,
        "label": label,
        "mode": mode,
        "adapter": adapter,
        "executable": executable,
        "description": description,
        "capabilities": capabilities,
        "models": models,
        "models_by_capability": models_by_capability,
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
        description="ChatGPT-authenticated Codex CLI for research, writing, review, and planning tasks.",
        docs_url="https://developers.openai.com/api/docs/models",
        command_template="codex exec --skip-git-repo-check --model {model} --output-last-message {output} - < {prompt}",
        options={"reasoning_effort": ["none", "low", "medium", "high", "xhigh", "max"]},
    ),
    "anthropic_api": _provider(
        "anthropic_api", "Claude API", mode="api", adapter="anthropic_api",
        capabilities=["structured"],
        models_by_capability={"structured": ["claude-fable-5", "claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"]},
        description="Anthropic Messages API with JSON-schema constrained structured output.",
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
        description="Subscription-backed Grok CLI for reasoning and built-in Imagine media tools.",
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
            "The Imagine API model and resolution are verified. Grok CLI exposes them through its built-in media tool, "
            "so the adapter requests these settings explicitly and records the returned result, but CLI releases may "
            "internally route the tool."
        ),
    ),
    "kimi_api": _provider(
        "kimi_api", "Kimi API", mode="api", adapter="kimi_api",
        capabilities=["structured"],
        models_by_capability={"structured": [
            "kimi-k3", "kimi-k2.7-code", "kimi-k2.7-code-highspeed", "kimi-k2.6", "kimi-k2.5",
        ]},
        description="Moonshot Kimi OpenAI-compatible API with JSON mode for structured pipeline tasks.",
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
        description="Google Gemini API for structured reasoning, Nano Banana images, and current video models.",
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
        "gemini_cli", "Gemini CLI", mode="command", adapter="command",
        executable="gemini", capabilities=["structured"],
        models_by_capability={"structured": [
            "auto", "pro", "flash", "flash-lite", "gemini-3.1-pro-preview",
            "gemini-3-flash-preview", "gemini-3.1-flash-lite",
            "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite",
        ]},
        description="Google-authenticated Gemini CLI. Model aliases follow the CLI's own routing and account availability.",
        docs_url="https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/model.md",
        command_template="gemini --model {model} --output-format json -p \"$(cat {prompt})\" > {output}",
        options={"reasoning_effort": ["low", "medium", "high"]},
    ),
    "openai_image_api": _provider(
        "openai_image_api", "OpenAI GPT Image API", mode="api", adapter="openai_image_api",
        capabilities=["image"],
        models_by_capability={"image": ["gpt-image-2", "gpt-image-2-2026-04-21"]},
        description="OpenAI Images API using GPT Image 2 for generation and editing.",
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
    ),
    "google_tts": _provider(
        "google_tts", "Google Gemini TTS", mode="api", adapter="google_tts",
        capabilities=["audio"],
        models_by_capability={"audio": [
            "gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts", "gemini-2.5-pro-preview-tts",
        ]},
        description="Google Gemini speech generation with steerable documentary delivery and expressive tags.",
        docs_url="https://ai.google.dev/gemini-api/docs/speech-generation",
        options={
            "audio": {
                "quality": ["fast", "balanced", "high_fidelity"],
                "voices": ["Kore", "Charon", "Fenrir", "Aoede", "Puck", "Leda", "Orus", "Zephyr"],
            }
        },
    ),
    "whisper_local": _provider(
        "whisper_local", "Local Whisper Alignment", mode="local", adapter="whisper_local",
        capabilities=["alignment"],
        models_by_capability={"alignment": ["tiny.en", "base.en", "small.en", "medium.en", "large-v3"]},
        description="Local word-level alignment from the approved voiceover. No LLM call or API cost.",
        docs_url="https://github.com/openai/whisper",
    ),
    "hyperframes": _provider(
        "hyperframes", "HyperFrames", mode="local", adapter="hyperframes",
        executable="hyperframes", capabilities=["render"],
        models_by_capability={"render": ["HyperFrames 0.7.62"]},
        description="Frame-accurate browser composition and deterministic MP4 rendering.",
        docs_url="https://github.com/hyperframes/hyperframes",
    ),
    "ffmpeg": _provider(
        "ffmpeg", "FFmpeg Renderer", mode="local", adapter="ffmpeg",
        executable="ffmpeg", capabilities=["render"],
        models_by_capability={"render": ["FFmpeg deterministic"]},
        description="Deterministic local animatic, final assembly, trimming, and audio muxing.",
        docs_url="https://ffmpeg.org/documentation.html",
        options={"render": {"resolutions": ["720p", "1080p", "1440p", "4K"]}},
    ),
    "manual_upload": _provider(
        "manual_upload", "Manual Upload / UI Handoff", mode="manual", adapter="manual",
        capabilities=["image", "video", "audio"],
        models_by_capability={"image": ["External image tool"], "video": ["External video tool"], "audio": ["External narration"]},
        description="Export prompts or import externally generated media while preserving the resumable contract.",
        docs_url="https://github.com/ananthcjayan12/failure-documentary-engine",
    ),
    "custom_cli": _provider(
        "custom_cli", "Custom CLI Adapter", mode="command", adapter="custom_cli",
        capabilities=["structured", "image", "video", "audio"],
        models_by_capability={
            "structured": ["custom-model"], "image": ["custom-image-model"],
            "video": ["custom-video-model"], "audio": ["custom-audio-model"],
        },
        description="Advanced escape hatch for a private CLI or local provider with explicit command templates.",
        docs_url="https://github.com/ananthcjayan12/failure-documentary-engine",
    ),
    "mock": _provider(
        "mock", "Offline Mock", mode="mock", adapter="mock",
        capabilities=["structured", "image", "video", "audio", "alignment", "render"],
        models_by_capability={capability: ["Deterministic Demo"] for capability in ["structured", "image", "video", "audio", "alignment", "render"]},
        description="Deterministic local provider for testing the complete workflow without paid calls.",
        docs_url="https://github.com/ananthcjayan12/failure-documentary-engine",
    ),
}


TASK_DEFINITIONS: list[dict[str, Any]] = [
    {"id": "research", "label": "Research dossier", "stage": 1, "pipeline_stage": "story_setup", "group": "Story setup", "capability": "structured", "description": "Build the source dossier, chronology, evidence list, and claim ledger."},
    {"id": "fact_verification", "label": "Fact verification", "stage": 1, "pipeline_stage": "story_setup", "group": "Story setup", "capability": "structured", "description": "Challenge unsupported claims and distinguish fact, inference, dispute, and theory."},
    {"id": "structure", "label": "Story structure", "stage": 1, "pipeline_stage": "story_setup", "group": "Story setup", "capability": "structured", "description": "Design chapters, reveals, escalation, and the ending."},
    {"id": "narration_writer", "label": "Narration writer", "stage": 2, "pipeline_stage": "narration", "group": "Narration", "capability": "structured", "description": "Write evidence-grounded spoken narration with sparse performance tags."},
    {"id": "narration_qa", "label": "Narration QA", "stage": 2, "pipeline_stage": "narration", "group": "Narration", "capability": "structured", "description": "Check claims, pacing, repetition, pronunciation risks, and TTS suitability."},
    {"id": "voice_generator", "label": "Documentary voice", "stage": 3, "pipeline_stage": "voice", "group": "Voice and timing", "capability": "audio", "description": "Generate chapter-cached narration and assemble the voice master."},
    {"id": "word_alignment", "label": "Word alignment", "stage": 3, "pipeline_stage": "voice", "group": "Voice and timing", "capability": "alignment", "description": "Create word timestamps tied to the current voiceover hash."},
    {"id": "shot_planner", "label": "Audio-led shot planner", "stage": 4, "pipeline_stage": "shots", "group": "Shots", "capability": "structured", "description": "Design visual beats after exact timing exists; local logic snaps boundaries to words and pauses."},
    {"id": "shot_qa", "label": "Shot-plan QA", "stage": 4, "pipeline_stage": "shots", "group": "Shots", "capability": "structured", "description": "Check coverage, visual repetition, continuity, and timing suitability."},
    {"id": "image_prompt_writer", "label": "Image prompt writer", "stage": 5, "pipeline_stage": "images", "group": "Images", "capability": "structured", "description": "Create technically credible, continuity-aware prompts for every approved shot."},
    {"id": "image_generator", "label": "Image generator", "stage": 5, "pipeline_stage": "images", "group": "Images", "capability": "image", "description": "Generate one primary still for each shot at the selected provider quality."},
    {"id": "image_qc", "label": "Image QC", "stage": 5, "pipeline_stage": "images", "group": "Images", "capability": "structured", "description": "Inspect geometry, continuity, prompt adherence, and animation readiness."},
    {"id": "animatic_renderer", "label": "Animatic renderer", "stage": 6, "pipeline_stage": "animatic", "group": "Image + sound preview", "capability": "render", "description": "Combine approved images, exact narration, and restrained ambience."},
    {"id": "animatic_qc", "label": "Animatic QA", "stage": 6, "pipeline_stage": "animatic", "group": "Image + sound preview", "capability": "structured", "description": "Review story clarity, shot length, repetition, and media-spend decisions."},
    {"id": "video_prompt_writer", "label": "Video prompt writer", "stage": 7, "pipeline_stage": "videos", "group": "Videos", "capability": "structured", "description": "Turn approved stills into restrained image-to-video briefs."},
    {"id": "video_generator", "label": "Video generator", "stage": 7, "pipeline_stage": "videos", "group": "Videos", "capability": "video", "description": "Generate selected clips with explicit model, resolution, duration, and aspect ratio."},
    {"id": "video_qc", "label": "Video QC", "stage": 7, "pipeline_stage": "videos", "group": "Videos", "capability": "structured", "description": "Inspect motion stability, geometry, identity preservation, and edit usefulness."},
    {"id": "final_renderer", "label": "Final preview renderer", "stage": 8, "pipeline_stage": "final_preview", "group": "Final preview", "capability": "render", "description": "Assemble approved videos, image fallbacks, and master narration."},
    {"id": "final_qc", "label": "Final preview QA", "stage": 8, "pipeline_stage": "final_preview", "group": "Final preview", "capability": "structured", "description": "Check continuity, stream integrity, pacing, and readiness for finishing."},
]
TASK_BY_ID = {item["id"]: item for item in TASK_DEFINITIONS}

# Saved workspaces created before the V1 router are migrated onto the new task names.
TASK_ALIASES = {
    "script": "narration_writer",
    "script_qa": "narration_qa",
    "timeline_builder": "shot_planner",
    "animation_prompt_writer": "video_prompt_writer",
    "composition_renderer": "final_renderer",
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
        "provider": provider,
        "model": model,
        "reasoning_effort": reasoning,
        "temperature": temperature,
        "timeout_seconds": timeout,
        "retry_count": retries,
        "fallback_provider": fallback_provider,
        "fallback_model": fallback_model,
        "quality": quality,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
        "duration_seconds": duration_seconds,
        "voice": voice,
        "enabled": True,
    }


DEFAULT_TASK_ROUTES: dict[str, dict[str, Any]] = {
    "research": route("codex", "gpt-5.6-sol", "high", 0.2, 1500, 1, "anthropic_api", "claude-sonnet-5"),
    "fact_verification": route("anthropic_api", "claude-sonnet-5", "high", 0.0, 1200, 1, "gemini_api", "gemini-3.5-flash"),
    "structure": route("anthropic_api", "claude-opus-4-8", "high", 0.4, 1500, 1, "codex", "gpt-5.6-sol"),
    "narration_writer": route("anthropic_api", "claude-sonnet-5", "high", 0.5, 1800, 1, "codex", "gpt-5.6-sol"),
    "narration_qa": route("kimi_api", "kimi-k3", "high", 0.0, 1200, 1, "gemini_api", "gemini-3.5-flash"),
    "voice_generator": route("google_tts", "gemini-3.1-flash-tts-preview", "standard", 0, 1800, 1, "manual_upload", "External narration", quality="balanced", voice="Kore"),
    "word_alignment": route("whisper_local", "base.en", "standard", 0, 3600, 0, "mock", "Deterministic Demo"),
    "shot_planner": route("gemini_api", "gemini-3.1-pro-preview", "high", 0.25, 1500, 1, "anthropic_api", "claude-sonnet-5"),
    "shot_qa": route("anthropic_api", "claude-sonnet-5", "high", 0.0, 900, 1, "gemini_api", "gemini-3.5-flash"),
    "image_prompt_writer": route("kimi_api", "kimi-k3", "high", 0.35, 1200, 1, "codex", "gpt-5.6-terra"),
    "image_generator": route("grok_cli", "grok-imagine-image-quality", "standard", 0, 3600, 1, "gemini_api", "gemini-3.1-flash-image", quality="quality", resolution="2K", aspect_ratio="16:9"),
    "image_qc": route("gemini_api", "gemini-3.5-flash", "medium", 0.0, 1200, 1, "anthropic_api", "claude-sonnet-5"),
    "animatic_renderer": route("ffmpeg", "FFmpeg deterministic", "standard", 0, 14400, 1, "hyperframes", "HyperFrames 0.7.62", resolution="720p", aspect_ratio="16:9"),
    "animatic_qc": route("gemini_api", "gemini-3.5-flash", "medium", 0.0, 1200, 1, "anthropic_api", "claude-sonnet-5"),
    "video_prompt_writer": route("anthropic_api", "claude-sonnet-5", "high", 0.3, 1200, 1, "kimi_api", "kimi-k3"),
    "video_generator": route("grok_cli", "grok-imagine-video-1.5", "standard", 0, 7200, 1, "gemini_api", "veo-3.1-fast-generate-preview", quality="standard", resolution="720p", aspect_ratio="16:9", duration_seconds=8),
    "video_qc": route("gemini_api", "gemini-3.5-flash", "medium", 0.0, 1200, 1, "anthropic_api", "claude-sonnet-5"),
    "final_renderer": route("ffmpeg", "FFmpeg deterministic", "standard", 0, 14400, 1, "hyperframes", "HyperFrames 0.7.62", resolution="1080p", aspect_ratio="16:9"),
    "final_qc": route("anthropic_api", "claude-sonnet-5", "high", 0.0, 1200, 1, "gemini_api", "gemini-3.5-flash"),
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
        if task_id not in result:
            continue
        result[task_id]["provider"] = provider
        result[task_id]["model"] = model
        result[task_id]["reasoning_effort"] = reasoning
    return result


PROFILES: dict[str, dict[str, Any]] = {
    "highest_quality": {
        "id": "highest_quality", "label": "Highest Quality",
        "description": "Claude and GPT-5.6 for core reasoning, Kimi/Gemini review, 2K Grok images, and 720p image-to-video.",
        "routes": _profile_routes(),
    },
    "balanced": {
        "id": "balanced", "label": "Balanced",
        "description": "GPT-5.6 Terra and Gemini Flash for most text work, standard Grok media, and local rendering.",
        "routes": _profile_routes({
            task["id"]: ("codex", "gpt-5.6-terra", "medium")
            for task in TASK_DEFINITIONS if task["capability"] == "structured"
        }),
    },
    "api_first": {
        "id": "api_first", "label": "API First",
        "description": "Claude, Kimi and Gemini APIs with no subscription CLI dependency except optional Grok media.",
        "routes": _profile_routes({
            "research": ("gemini_api", "gemini-3.5-flash", "high"),
            "structure": ("anthropic_api", "claude-opus-4-8", "high"),
            "narration_writer": ("anthropic_api", "claude-sonnet-5", "high"),
            "image_generator": ("gemini_api", "gemini-3.1-flash-image", "standard"),
            "video_generator": ("gemini_api", "veo-3.1-fast-generate-preview", "standard"),
        }),
    },
    "subscription_cli": {
        "id": "subscription_cli", "label": "Subscription CLI",
        "description": "Codex, Gemini CLI and Grok CLI minimize API usage while keeping the same V1 gates.",
        "routes": _profile_routes({
            **{task["id"]: ("codex", "gpt-5.6-terra", "medium") for task in TASK_DEFINITIONS if task["capability"] == "structured"},
            "narration_qa": ("gemini_cli", "flash", "medium"),
            "shot_qa": ("gemini_cli", "pro", "high"),
        }),
    },
    "fast_low_cost": {
        "id": "fast_low_cost", "label": "Fast / Low Cost",
        "description": "Kimi K2.7 high-speed, Gemini Flash-Lite, 1K images, 480p video, and FFmpeg.",
        "routes": _profile_routes({
            **{task["id"]: ("kimi_api", "kimi-k2.7-code-highspeed", "low") for task in TASK_DEFINITIONS if task["capability"] == "structured"},
            "image_qc": ("gemini_api", "gemini-3.5-flash-lite", "low"),
            "video_qc": ("gemini_api", "gemini-3.5-flash-lite", "low"),
        }),
    },
    "offline": {
        "id": "offline", "label": "Offline Test",
        "description": "No external calls; validates restart, routing, media, and rendering contracts.",
        "routes": {
            task["id"]: route("mock", "Deterministic Demo", "low", 0, 120, 0, "mock", "Deterministic Demo")
            for task in TASK_DEFINITIONS
        },
    },
}
# Apply profile-specific media controls after creation.
PROFILES["balanced"]["routes"]["image_generator"].update({"resolution": "1K", "quality": "standard"})
PROFILES["balanced"]["routes"]["video_generator"].update({"resolution": "720p"})
PROFILES["api_first"]["routes"]["image_generator"].update({"resolution": "2K", "aspect_ratio": "16:9"})
PROFILES["api_first"]["routes"]["video_generator"].update({"resolution": "720p", "aspect_ratio": "16:9", "duration_seconds": 8})
PROFILES["fast_low_cost"]["routes"]["image_generator"].update({"model": "grok-imagine-image", "resolution": "1K", "quality": "standard"})
PROFILES["fast_low_cost"]["routes"]["video_generator"].update({"model": "grok-imagine-video", "resolution": "480p", "duration_seconds": 5})


DEFAULT_RULES: list[dict[str, Any]] = [
    {
        "id": "long_narration_quality", "label": "Long documentary narration", "enabled": True,
        "task_id": "narration_writer", "field": "duration_seconds", "operator": ">", "value": 600,
        "provider": "anthropic_api", "model": "claude-fable-5", "reasoning_effort": "high",
    }
]


def default_orchestrator_config() -> dict[str, Any]:
    return {
        "version": 3,
        "active_profile": "highest_quality",
        "active_prompt_pack": "aviation_investigation",
        "tasks": copy.deepcopy(DEFAULT_TASK_ROUTES),
        "providers": {
            key: {
                "command_template": value.get("command_template", ""),
                "media_command_template": value.get("media_command_template", ""),
                "enabled": True,
            }
            for key, value in PROVIDERS.items()
        },
        "prompt_packs": copy.deepcopy(PROMPT_PACKS),
        "rules": copy.deepcopy(DEFAULT_RULES),
    }


def merge_orchestrator_config(saved: dict[str, Any] | None) -> dict[str, Any]:
    config = default_orchestrator_config()
    saved = saved or {}
    for key in ("active_profile", "active_prompt_pack"):
        if key in saved:
            config[key] = saved[key]
    saved_tasks = saved.get("tasks", {}) if isinstance(saved.get("tasks"), dict) else {}
    for raw_task_id, values in saved_tasks.items():
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
        config["rules"] = [
            ({**item, "task_id": TASK_ALIASES.get(item.get("task_id"), item.get("task_id"))} if isinstance(item, dict) else item)
            for item in saved["rules"]
        ]
    config["version"] = 3
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
    enabled = bool(overrides.get("enabled", True))
    if not enabled:
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
            "provider_id": provider_id,
            "status": "ready" if configured else "unconfigured",
            "healthy": configured,
            "detail": f"{names[0]} configured" if configured else f"Set {' or '.join(names)} before starting Studio",
        }
    if provider_id == "whisper_local":
        found = importlib.util.find_spec("whisper") is not None
        return {
            "provider_id": provider_id, "status": "ready" if found else "missing", "healthy": found,
            "detail": "openai-whisper installed" if found else "Install the optional alignment dependency: pip install -e '.[alignment]'",
        }
    if provider_id == "custom_cli":
        configured = bool((overrides.get("command_template") or "").strip() or (overrides.get("media_command_template") or "").strip())
        return {"provider_id": provider_id, "status": "ready" if configured else "unconfigured", "healthy": configured, "detail": "Custom command configured" if configured else "Add a command template"}
    if provider_id == "hyperframes":
        root = Path(__file__).resolve().parents[1]
        found = bool(shutil.which("hyperframes") or (root / "node_modules/.bin/hyperframes").exists() or shutil.which("npx"))
        return {"provider_id": provider_id, "status": "ready" if found else "missing", "healthy": found, "detail": "HyperFrames runtime available" if found else "Run npm install in the repository"}
    executable = provider.get("executable")
    found = bool(executable and shutil.which(executable))
    return {
        "provider_id": provider_id, "status": "ready" if found else "missing", "healthy": found,
        "detail": f"{executable} found on PATH" if found else f"Install or expose the {executable} executable",
    }


def _models_for(provider: dict[str, Any], capability: str) -> list[str]:
    return list(provider.get("models_by_capability", {}).get(capability, []))


def _validate_media_settings(provider: dict[str, Any], capability: str, route_config: dict[str, Any]) -> None:
    if capability not in {"image", "video"}:
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
            for key in (
                "provider", "model", "reasoning_effort", "temperature", "timeout_seconds", "retry_count",
                "quality", "resolution", "aspect_ratio", "duration_seconds", "voice",
            ):
                if key in rule:
                    resolved[key] = rule[key]
            resolved["matched_rule"] = rule.get("label") or rule.get("id")
            break
    provider_id = resolved.get("provider", "mock")
    if provider_id not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider_id}")
    provider = PROVIDERS[provider_id]
    required_capability = definition["capability"]
    if required_capability not in provider.get("capabilities", []):
        raise ValueError(f"Provider {provider_id} cannot execute {required_capability} task {task_id}")
    models = _models_for(provider, required_capability)
    selected_model = resolved.get("model", "")
    if models and selected_model not in models and provider_id != "custom_cli":
        raise ValueError(f"Model {selected_model} is not a verified {required_capability} model for {provider['label']}")
    _validate_media_settings(provider, required_capability, resolved)
    provider_override = config.get("providers", {}).get(provider_id, {})
    resolved.update({
        "task_id": task_id,
        "pipeline_stage": definition["pipeline_stage"],
        "capability": required_capability,
        "provider_mode": provider["mode"],
        "provider_adapter": provider.get("adapter", provider["mode"]),
        "provider_label": provider["label"],
        "provider_docs_url": provider.get("docs_url", ""),
        "provider_docs_checked_at": provider.get("docs_checked_at", ""),
        "command_template": provider_override.get("command_template") or provider.get("command_template", ""),
        "media_command_template": provider_override.get("media_command_template") or provider.get("media_command_template", ""),
    })
    fallback_id = resolved.get("fallback_provider")
    fallback = PROVIDERS.get(fallback_id, {})
    if fallback_id and required_capability not in fallback.get("capabilities", []):
        raise ValueError(f"Fallback provider {fallback_id} cannot execute {required_capability} task {task_id}")
    if fallback_id:
        fallback_models = _models_for(fallback, required_capability)
        fallback_model = resolved.get("fallback_model", "")
        if fallback_models and fallback_model not in fallback_models and fallback_id != "custom_cli":
            raise ValueError(f"Fallback model {fallback_model} is not verified for {fallback.get('label', fallback_id)}")
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
    tasks = []
    for definition in TASK_DEFINITIONS:
        task_id = definition["id"]
        route_config = config.get("tasks", {}).get(task_id, DEFAULT_TASK_ROUTES[task_id])
        item = copy.deepcopy(definition)
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
        "docs_checked_at": DOCS_CHECKED_AT,
    }


def _matches(actual: Any, operator: str | None, expected: Any) -> bool:
    try:
        if operator == ">":
            return float(actual) > float(expected)
        if operator == ">=":
            return float(actual) >= float(expected)
        if operator == "<":
            return float(actual) < float(expected)
        if operator == "<=":
            return float(actual) <= float(expected)
        if operator == "contains":
            return str(expected).lower() in str(actual).lower()
        if operator == "==":
            return str(actual) == str(expected)
    except (TypeError, ValueError):
        return False
    return False
