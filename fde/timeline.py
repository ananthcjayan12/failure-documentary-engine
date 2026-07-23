from __future__ import annotations

from pathlib import Path

from .io import load_model, write_json
from .master_footage import approved_master_plan
from .models import (
    EditorialShotPlan,
    OverlaySpec,
    Timeline,
    TimelineEntry,
    V1MediaManifest,
)


def _media_jobs(project_dir: Path, media_type: str) -> dict:
    path = project_dir / ("07_images/jobs.json" if media_type == "image" else "09_videos/jobs.json")
    if not path.exists():
        return {}
    manifest = load_model(path, V1MediaManifest)
    return {item.asset_id or item.shot_id: item for item in manifest.jobs}


def build_timeline(project_dir: Path) -> Timeline:
    """Build exact editorial timing with separate source and timeline semantics."""
    project_dir = Path(project_dir)
    editorial = load_model(
        project_dir / "06_shots/editorial_shot_plan.json",
        EditorialShotPlan,
    )
    master_plan = approved_master_plan(project_dir)
    assets = {item.asset_id: item for item in master_plan.assets}
    images = _media_jobs(project_dir, "image")
    videos = _media_jobs(project_dir, "video")
    overlays: dict[str, OverlaySpec] = {}
    entries: list[TimelineEntry] = []

    for index, shot in enumerate(editorial.shots, start=1):
        source = ""
        kind = "placeholder"
        master_asset = shot.master_asset_id or ""
        if shot.visual_mode in {
            "master_video",
            "master_video_with_overlay",
            "master_video_freeze",
            "generated_still",
        }:
            if not master_asset or master_asset not in assets:
                raise ValueError(f"{shot.shot_id} has no approved master asset")
            video = videos.get(master_asset)
            image = images.get(master_asset)
            if (
                shot.visual_mode != "master_video_freeze"
                and video
                and video.status == "approved"
                and video.output
            ):
                source = video.output
                kind = "video"
            elif image and image.status == "approved" and image.output:
                source = image.output
                kind = "image"
        elif shot.visual_mode == "coded_graphic":
            kind = "coded_graphic"
        elif shot.visual_mode == "archive_media":
            source = shot.archive_source or ""
            kind = "archive"
        elif shot.visual_mode == "black_or_negative_space":
            kind = "placeholder"

        overlay_ids: list[str] = []
        if shot.overlay:
            overlay_id = f"OVL_{index:03d}"
            overlays[overlay_id] = shot.overlay
            overlay_ids.append(overlay_id)
            write_json(
                project_dir / "12_timeline/overlays" / f"{overlay_id}.json",
                shot.overlay,
            )

        source_out = shot.source_out
        if source_out is None and master_asset in assets:
            source_out = assets[master_asset].source_duration_seconds
        entries.append(
            TimelineEntry(
                timeline_id=f"TL_{index:03d}",
                shot_id=shot.shot_id,
                timeline_start=shot.start,
                timeline_end=shot.end,
                narration_ids=shot.narration_ids,
                master_asset=master_asset,
                source_media=source,
                media_kind=kind,
                visual_mode=shot.visual_mode,
                playback_mode=shot.reuse_operation,
                playback_speed=shot.playback_speed,
                source_in=shot.source_in,
                source_out=source_out,
                crop_id=shot.crop_id,
                overlay_track_ids=overlay_ids,
                trim_in=shot.source_in,
                trim_out=source_out,
                transition_out=shot.transition,
            )
        )
    timeline = Timeline(
        project_id=editorial.project_id,
        entries=entries,
        total_seconds=editorial.total_seconds,
        overlay_tracks=overlays,
    )
    write_json(project_dir / "12_timeline/timeline.json", timeline)
    write_json(
        project_dir / "12_timeline/overlay_tracks.json",
        {key: value.model_dump(mode="json") for key, value in overlays.items()},
    )
    return timeline
