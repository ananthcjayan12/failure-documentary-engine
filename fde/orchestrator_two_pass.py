from __future__ import annotations

"""Two-pass routing overlay.

The provider catalogue remains in :mod:`fde.orchestrator`. This module updates the
executable task graph so the Studio routes the master-footage planner and editorial
director separately while the shot skeleton stays deterministic and local.
"""

import copy
from typing import Any

from . import orchestrator as _base


NEW_TASKS: list[dict[str, Any]] = [
    {
        "id": "research",
        "label": "Research dossier",
        "stage": 1,
        "pipeline_stage": "story_setup",
        "group": "Story setup",
        "capability": "structured",
        "description": "Build the source dossier, chronology, evidence list, and claim ledger.",
    },
    {
        "id": "structure",
        "label": "Story structure",
        "stage": 1,
        "pipeline_stage": "story_setup",
        "group": "Story setup",
        "capability": "structured",
        "description": "Design chapters, escalation, reveals, and the ending.",
    },
    {
        "id": "narration_writer",
        "label": "Narration writer",
        "stage": 2,
        "pipeline_stage": "narration",
        "group": "Narration",
        "capability": "structured",
        "description": "Write evidence-grounded spoken narration with sparse performance tags.",
    },
    {
        "id": "voice_generator",
        "label": "Documentary voice",
        "stage": 3,
        "pipeline_stage": "voice",
        "group": "Voice and timing",
        "capability": "audio",
        "description": "Generate chapter-cached narration and assemble the voice master.",
    },
    {
        "id": "word_alignment",
        "label": "Word alignment",
        "stage": 3,
        "pipeline_stage": "voice",
        "group": "Voice and timing",
        "capability": "alignment",
        "description": "Create word timestamps tied to the current voiceover hash.",
    },
    {
        "id": "master_footage_planner",
        "label": "24-package footage planner",
        "stage": 5,
        "pipeline_stage": "master_footage",
        "group": "Master footage",
        "capability": "structured",
        "description": (
            "Select exactly 8 hero, 8 loopable atmosphere, and 8 investigation packages "
            "before editorial shot direction."
        ),
    },
    {
        "id": "editorial_director",
        "label": "Approved-package editorial director",
        "stage": 6,
        "pipeline_stage": "shots",
        "group": "Editorial shots",
        "capability": "structured",
        "description": (
            "Assign approved packages, crops, loop/freeze behaviour, and typed overlays to "
            "immutable audio-led shot boundaries."
        ),
    },
    {
        "id": "image_generator",
        "label": "Master-package image generator",
        "stage": 7,
        "pipeline_stage": "images",
        "group": "Images",
        "capability": "image",
        "description": "Generate exactly one primary still for each approved master-footage package.",
    },
    {
        "id": "animatic_renderer",
        "label": "Editorial animatic renderer",
        "stage": 8,
        "pipeline_stage": "animatic",
        "group": "Image + sound preview",
        "capability": "render",
        "description": "Apply crop, loop, freeze, coded overlays, narration, and restrained ambience.",
    },
    {
        "id": "video_generator",
        "label": "Master-package video generator",
        "stage": 9,
        "pipeline_stage": "videos",
        "group": "Videos",
        "capability": "video",
        "description": "Generate exactly one configured-duration source clip per approved package.",
    },
    {
        "id": "final_renderer",
        "label": "Final editorial renderer",
        "stage": 10,
        "pipeline_stage": "final_preview",
        "group": "Final preview",
        "capability": "render",
        "description": "Assemble source packages with editorial playback and deterministic overlays.",
    },
]


def _structured_route_like(task_id: str) -> dict[str, Any]:
    source = _base.DEFAULT_TASK_ROUTES.get(task_id) or _base.DEFAULT_TASK_ROUTES["narration_writer"]
    return copy.deepcopy(source)


NEW_ROUTES = copy.deepcopy(_base.DEFAULT_TASK_ROUTES)
old_shot_route = NEW_ROUTES.pop("shot_planner", _structured_route_like("narration_writer"))
NEW_ROUTES["master_footage_planner"] = copy.deepcopy(old_shot_route)
NEW_ROUTES["master_footage_planner"].update(
    {
        "provider": "anthropic_api",
        "model": "claude-sonnet-5",
        "reasoning_effort": "high",
        "temperature": 0.25,
        "fallback_provider": "",
        "fallback_model": "",
    }
)
NEW_ROUTES["editorial_director"] = copy.deepcopy(old_shot_route)
NEW_ROUTES["editorial_director"].update(
    {
        "provider": "gemini_api",
        "model": "gemini-3.1-pro-preview",
        "reasoning_effort": "high",
        "temperature": 0.2,
    }
)

_base.TASK_DEFINITIONS[:] = NEW_TASKS
_base.TASK_BY_ID.clear()
_base.TASK_BY_ID.update({item["id"]: item for item in NEW_TASKS})
_base.DEFAULT_TASK_ROUTES.clear()
_base.DEFAULT_TASK_ROUTES.update(NEW_ROUTES)
_base.TASK_ALIASES.update(
    {
        "shot_planner": "editorial_director",
        "asset_optimizer": "master_footage_planner",
        "image_prompt_writer": "master_footage_planner",
        "animation_prompt_writer": "editorial_director",
        "video_prompt_writer": "editorial_director",
        "timeline_builder": "editorial_director",
        "shot_qa": "editorial_director",
    }
)

# Rebuild every profile against the new executable graph while preserving the user's
# existing provider and media preferences.
for profile in _base.PROFILES.values():
    routes = profile.get("routes", {})
    old = routes.pop("shot_planner", None)
    profile["routes"] = {
        task["id"]: copy.deepcopy(
            routes.get(task["id"])
            or (
                old
                if task["id"] in {"master_footage_planner", "editorial_director"} and old
                else NEW_ROUTES[task["id"]]
            )
        )
        for task in NEW_TASKS
    }

# Give the built-in profiles intentional two-pass choices.
profile_overrides = {
    "balanced": {
        "master_footage_planner": ("anthropic_api", "claude-sonnet-5", "high"),
        "editorial_director": ("gemini_api", "gemini-3.5-flash", "high"),
    },
    "api_first": {
        "master_footage_planner": ("anthropic_api", "claude-sonnet-5", "high"),
        "editorial_director": ("gemini_api", "gemini-3.1-pro-preview", "high"),
    },
    "subscription_cli": {
        "master_footage_planner": ("anthropic_api", "claude-sonnet-5", "high"),
        "editorial_director": ("codex", "gpt-5.6-sol", "high"),
    },
    "fast_low_cost": {
        "master_footage_planner": ("anthropic_api", "claude-sonnet-5", "high"),
        "editorial_director": ("gemini_api", "gemini-3.5-flash-lite", "low"),
    },
}
for profile_id, values in profile_overrides.items():
    profile = _base.PROFILES.get(profile_id)
    if not profile:
        continue
    for task_id, (provider, model, reasoning) in values.items():
        profile["routes"][task_id].update(
            {
                "provider": provider,
                "model": model,
                "reasoning_effort": reasoning,
                **({"fallback_provider": "", "fallback_model": ""} if task_id == "master_footage_planner" else {}),
            }
        )

# All public helpers execute against the mutated base module globals.
DOCS_CHECKED_AT = _base.DOCS_CHECKED_AT
CONFIG_VERSION = max(getattr(_base, "CONFIG_VERSION", 1), 5)
PROVIDERS = _base.PROVIDERS
TASK_DEFINITIONS = _base.TASK_DEFINITIONS
TASK_BY_ID = _base.TASK_BY_ID
TASK_ALIASES = _base.TASK_ALIASES
DEFAULT_TASK_ROUTES = _base.DEFAULT_TASK_ROUTES
PROMPT_PACKS = _base.PROMPT_PACKS
PROFILES = _base.PROFILES
DEFAULT_RULES = _base.DEFAULT_RULES
route = _base.route
default_orchestrator_config = _base.default_orchestrator_config
merge_orchestrator_config = _base.merge_orchestrator_config
resolve_task = _base.resolve_task
public_payload = _base.public_payload
provider_health = _base.provider_health
apply_profile = _base.apply_profile
