from __future__ import annotations

from pathlib import Path

from .io import load_model, write_json
from .models import EditorialShotPlan, V1MediaManifest, utc_now
from .project import ProjectStore


def _mark_asset_job_stale(project: Path, media_type: str, asset_id: str) -> bool:
    path = project / ("07_images/jobs.json" if media_type == "image" else "09_videos/jobs.json")
    if not path.exists():
        return False
    manifest = load_model(path, V1MediaManifest)
    changed = False
    for job in manifest.jobs:
        if (job.asset_id or job.shot_id) != asset_id:
            continue
        job.status = "pending"
        job.error = f"invalidated because master package {asset_id} changed"
        job.updated_at = utc_now()
        changed = True
    if changed:
        write_json(path, manifest)
    return changed


def invalidate_master_asset(
    store: ProjectStore,
    project_id: str,
    asset_id: str,
) -> list[str]:
    """Invalidate only one package and its derived edit/render outputs."""
    asset_id = asset_id.upper()
    project = store.project_dir(project_id)
    affected_shots: list[str] = []
    editorial_path = project / "06_shots/editorial_shot_plan.json"
    if editorial_path.exists():
        editorial = load_model(editorial_path, EditorialShotPlan)
        affected_shots = [
            item.shot_id for item in editorial.shots if item.master_asset_id == asset_id
        ]
    targets = [
        f"asset:{asset_id}:image",
        f"asset:{asset_id}:video",
        f"asset:{asset_id}:variants",
        *[f"timeline:{shot_id}" for shot_id in affected_shots],
        "preview:animatic",
        "preview:final",
    ]
    _mark_asset_job_stale(project, "image", asset_id)
    _mark_asset_job_stale(project, "video", asset_id)
    store.invalidate(project_id, targets)
    write_json(
        project / "_jobs/invalidation" / f"asset-{asset_id}.json",
        {
            "project_id": project_id,
            "asset_id": asset_id,
            "affected_shots": affected_shots,
            "targets": targets,
            "created_at": utc_now(),
        },
    )
    return targets


def invalidate_overlay(
    store: ProjectStore,
    project_id: str,
    overlay_id: str,
) -> list[str]:
    """Invalidate one coded overlay and only the timeline entries that reference it."""
    overlay_id = overlay_id.upper()
    project = store.project_dir(project_id)
    affected: list[str] = []
    timeline_path = project / "12_timeline/timeline.json"
    if timeline_path.exists():
        raw = __import__("json").loads(timeline_path.read_text(encoding="utf-8"))
        affected = [
            item.get("shot_id", "")
            for item in raw.get("entries", [])
            if overlay_id in item.get("overlay_track_ids", [])
        ]
    targets = [
        f"overlay:{overlay_id}",
        *[f"timeline:{shot_id}" for shot_id in affected if shot_id],
        "preview:animatic",
        "preview:final",
    ]
    store.invalidate(project_id, targets)
    write_json(
        project / "_jobs/invalidation" / f"overlay-{overlay_id}.json",
        {
            "project_id": project_id,
            "overlay_id": overlay_id,
            "affected_shots": affected,
            "targets": targets,
            "created_at": utc_now(),
        },
    )
    return targets
