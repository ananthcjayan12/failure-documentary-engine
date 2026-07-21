from __future__ import annotations

from pathlib import Path

from .io import load_model, read_json, write_json
from .models import (
    DocumentaryScript,
    MasterAssetPlan,
    NarrationTimestamp,
    ShotPlan,
    Timeline,
    TimelineEntry,
)


def build_timeline(project_dir: Path) -> Timeline:
    shot_plan = load_model(project_dir / "04_shot_plan/shot_plan.json", ShotPlan)
    assets = load_model(project_dir / "05_master_assets/master_assets.json", MasterAssetPlan)
    script = load_model(project_dir / "03_script/script.json", DocumentaryScript)
    narration_times = {
        n.narration_id: (n.estimated_start, n.estimated_start + n.estimated_duration)
        for n in script.segments
    }
    timestamps_path = project_dir / "11_narration/word_timestamps.json"
    if timestamps_path.exists():
        raw = read_json(timestamps_path)
        parsed = [NarrationTimestamp.model_validate(item) for item in raw]
        narration_times.update({x.narration_id: (x.start, x.end) for x in parsed})

    asset_for_shot: dict[str, object] = {}
    for asset in assets.assets:
        for shot_id in asset.linked_shots:
            asset_for_shot[shot_id] = asset

    entries: list[TimelineEntry] = []
    for index, shot in enumerate(sorted(shot_plan.shots, key=lambda s: s.start), 1):
        asset = asset_for_shot.get(shot.shot_id)
        if asset is None:
            raise ValueError(f"shot has no master asset: {shot.shot_id}")
        starts = [narration_times[n][0] for n in shot.narration_ids if n in narration_times]
        ends = [narration_times[n][1] for n in shot.narration_ids if n in narration_times]
        # Retain shot subdivision while adapting to actual narration boundaries.
        start = shot.start if not starts else max(shot.start, min(starts))
        end = start + shot.duration
        if ends:
            end = min(max(ends), end)
            if end <= start:
                end = start + shot.duration
        if asset.approved_video:
            source = asset.approved_video
            kind = "video"
        elif asset.approved_image:
            source = asset.approved_image
            kind = "image"
        else:
            source = ""
            kind = "placeholder"
        entries.append(
            TimelineEntry(
                timeline_id=f"TL_{index:03d}", shot_id=shot.shot_id,
                start=start, end=end, narration_ids=shot.narration_ids,
                master_asset=asset.asset_id, source_media=source, media_kind=kind,
                trim_out=max(0.1, end - start),
                transition_out="crossfade_8_frames" if index % 4 == 0 else "hard_cut",
            )
        )
    total = max((e.end for e in entries), default=0)
    timeline = Timeline(project_id=shot_plan.project_id, entries=entries, total_seconds=total)
    write_json(project_dir / "12_timeline/timeline.json", timeline)
    return timeline
