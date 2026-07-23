from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .editorial import approve_editorial_shots, direct_editorial_shots
from .master_footage import approve_master_footage, plan_master_footage
from .models import ProjectBrief, ProjectState
from .pipeline import (
    generate_research,
    generate_script,
    generate_shot_skeleton_stage,
    generate_structure,
    generate_timing_stage,
    generate_voice_stage,
)
from .project import ProjectStore
from .v1_media import generate_media_jobs, prepare_media_jobs


def create_demo(store: ProjectStore, project_id: str) -> Path:
    """Create an offline two-pass demo through package-image review."""
    brief = ProjectBrief(
        project_id=project_id,
        title="MH370 Demo Investigation",
        topic="Demonstration project for a missing-aircraft investigation documentary",
        target_duration_seconds=480,
        maximum_master_assets=24,
    )
    project_dir = store.create(brief)
    generate_research(store, project_id, "mock")
    generate_structure(store, project_id, "mock")
    store.approve_version(project_id, "structure")
    store.transition(project_id, ProjectState.STRUCTURE_APPROVED)
    generate_script(store, project_id, "mock")
    store.approve_version(project_id, "narration")
    store.transition(project_id, ProjectState.NARRATION_APPROVED)
    generate_voice_stage(store, project_id, provider="mock")
    store.transition(project_id, ProjectState.VOICE_APPROVED)
    generate_timing_stage(store, project_id)
    generate_shot_skeleton_stage(store, project_id)
    store.approve_version(project_id, "shot_skeleton")
    store.transition(project_id, ProjectState.SHOT_SKELETON_APPROVED)
    plan_master_footage(store, project_id, agent_kind="deterministic")
    approve_master_footage(store, project_id)
    direct_editorial_shots(store, project_id, agent_kind="deterministic")
    approve_editorial_shots(store, project_id)
    prepare_media_jobs(project_dir, "image")
    generate_media_jobs(
        project_dir,
        media_type="image",
        route={
            "provider": "mock",
            "model": "Deterministic Demo",
            "timeout": 30,
            "command": "",
            "resolution": "2K",
            "aspect_ratio": "16:9",
        },
    )
    store.transition(project_id, ProjectState.IMAGES_REVIEW)
    return project_dir


def _demo_image(path: Path, asset_id: str, title: str, index: int) -> None:
    """Retained for old callers that import this helper directly."""
    width, height = 1600, 900
    image = Image.new(
        "RGB",
        (width, height),
        (8 + index * 3 % 20, 28 + index * 5 % 40, 41 + index * 7 % 50),
    )
    draw = ImageDraw.Draw(image)
    try:
        big = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 110
        )
        small = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 48
        )
    except Exception:
        big = small = ImageFont.load_default()
    draw.text((90, 90), asset_id, font=big, fill=(239, 246, 248))
    draw.text((90, 250), title[:58], font=small, fill=(218, 225, 225))
    image.save(path)
