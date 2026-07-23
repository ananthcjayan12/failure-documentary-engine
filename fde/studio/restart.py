from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..io import write_json
from ..models import ProjectState, utc_now
from ..project import ProjectStore


@dataclass(frozen=True)
class RestartSpec:
    stage_id: str
    reset_state: ProjectState
    run_action: str
    archive_paths: tuple[str, ...]
    version_keys: tuple[str, ...]


MEDIA_DOWNSTREAM = (
    "07_images",
    "08_animatic",
    "09_videos",
    "10_final_preview",
    "06_contact_sheet",
    "07_review",
    "08_generated_images",
    "09_video_jobs",
    "10_generated_videos",
    "12_timeline",
    "13_preview",
    "14_final",
)

RESTART_SPECS: dict[str, RestartSpec] = {
    "story_setup": RestartSpec(
        "story_setup",
        ProjectState.PROJECT_CREATED,
        "research",
        (
            "01_research", "02_structure", "03_narration", "03_script", "04_voice",
            "05_timing", "05_master_assets", "06_shots", "04_shot_plan", "11_narration",
            "_requests", *MEDIA_DOWNSTREAM,
        ),
        (
            "research", "structure", "narration", "script", "shot_skeleton",
            "master_footage", "editorial_shots", "shots",
        ),
    ),
    "narration": RestartSpec(
        "narration",
        ProjectState.STRUCTURE_APPROVED,
        "narration",
        (
            "03_narration", "03_script", "04_voice", "05_timing", "05_master_assets",
            "06_shots", "04_shot_plan", "11_narration", "_requests", *MEDIA_DOWNSTREAM,
        ),
        (
            "narration", "script", "shot_skeleton", "master_footage",
            "editorial_shots", "shots",
        ),
    ),
    "voice": RestartSpec(
        "voice",
        ProjectState.NARRATION_APPROVED,
        "generate_voice",
        (
            "04_voice", "05_timing", "05_master_assets", "06_shots", "04_shot_plan",
            "11_narration", *MEDIA_DOWNSTREAM,
        ),
        ("shot_skeleton", "master_footage", "editorial_shots", "shots"),
    ),
    "shot_skeleton": RestartSpec(
        "shot_skeleton",
        ProjectState.VOICE_APPROVED,
        "shot_skeleton",
        ("06_shots", "04_shot_plan", "05_master_assets", *MEDIA_DOWNSTREAM),
        ("shot_skeleton", "master_footage", "editorial_shots", "shots"),
    ),
    "master_footage": RestartSpec(
        "master_footage",
        ProjectState.SHOT_SKELETON_APPROVED,
        "master_footage",
        ("05_master_assets", "06_shots/editorial_shot_plan.json", *MEDIA_DOWNSTREAM),
        ("master_footage", "editorial_shots", "shots"),
    ),
    "shots": RestartSpec(
        "shots",
        ProjectState.MASTER_PLAN_APPROVED,
        "editorial_shots",
        ("06_shots/editorial_shot_plan.json", "04_shot_plan", *MEDIA_DOWNSTREAM),
        ("editorial_shots", "shots"),
    ),
    "images": RestartSpec(
        "images",
        ProjectState.SHOTS_APPROVED,
        "prepare_images",
        MEDIA_DOWNSTREAM,
        (),
    ),
    "animatic": RestartSpec(
        "animatic",
        ProjectState.IMAGES_APPROVED,
        "render_animatic",
        (
            "08_animatic", "09_videos", "10_final_preview", "10_generated_videos",
            "12_timeline", "13_preview", "14_final",
        ),
        (),
    ),
    "videos": RestartSpec(
        "videos",
        ProjectState.ANIMATIC_APPROVED,
        "prepare_videos",
        (
            "09_videos", "10_final_preview", "10_generated_videos", "12_timeline",
            "13_preview", "14_final",
        ),
        (),
    ),
    "final_preview": RestartSpec(
        "final_preview",
        ProjectState.VIDEOS_APPROVED,
        "render_final_preview",
        ("10_final_preview", "13_preview", "14_final"),
        (),
    ),
}


def restart_stage(store: ProjectStore, project_id: str, stage_id: str) -> dict[str, Any]:
    if stage_id not in RESTART_SPECS:
        raise ValueError(f"Unknown production stage: {stage_id}")
    spec = RESTART_SPECS[stage_id]
    project = store.project_dir(project_id)
    if not project.exists():
        raise FileNotFoundError(project_id)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    history = project / "_history" / f"{timestamp}-{stage_id}"
    archived: list[str] = []
    for relative in dict.fromkeys(spec.archive_paths):
        source = project / relative
        if not source.exists():
            continue
        destination = history / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        archived.append(relative)
        if source.suffix:
            source.parent.mkdir(parents=True, exist_ok=True)
        else:
            source.mkdir(parents=True, exist_ok=True)
    manifest = store.manifest(project_id)
    for key in spec.version_keys:
        manifest.current_versions.pop(key, None)
        manifest.approved_versions.pop(key, None)
    manifest.invalidated_targets = []
    manifest.state = spec.reset_state
    store.save_manifest(manifest)
    report = {
        "project_id": project_id,
        "stage_id": stage_id,
        "reset_state": spec.reset_state.value,
        "run_action": spec.run_action,
        "archived": archived,
        "history_path": str(history.relative_to(project)),
        "created_at": utc_now(),
    }
    write_json(history / "restart.json", report)
    return report
