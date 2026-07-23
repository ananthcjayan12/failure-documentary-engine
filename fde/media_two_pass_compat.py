from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import load_model, write_json
from .models import MasterAssetPlan
from .providers import media_factory as _base

_ORIGINAL_GENERATE_PROJECT_MEDIA = _base.generate_project_media


def _synchronize_generation_contract(project_dir: Path) -> None:
    master_path = project_dir / "05_master_assets/master_assets.json"
    generation_path = project_dir / "05_master_assets/generation_plan.json"
    if not master_path.exists() or not generation_path.exists():
        return
    master = load_model(master_path, MasterAssetPlan)
    generated = load_model(generation_path, MasterAssetPlan)
    generated_by_id = {item.asset_id: item for item in generated.assets}
    for asset in master.assets:
        source = generated_by_id.get(asset.asset_id)
        if source is None:
            continue
        asset.image_prompt = source.image_prompt
        asset.video_prompt = source.video_prompt
        # Media state is allowed to move in either direction between the modern
        # package jobs and the legacy generation/import compatibility paths.
        if source.approved_image:
            asset.approved_image = source.approved_image
            asset.image_version = source.image_version
            asset.image_review = source.image_review
        if source.approved_video:
            asset.approved_video = source.approved_video
            asset.video_version = source.video_version
            asset.video_review = source.video_review
    write_json(master_path, master)


def generate_project_media(
    project_dir: Path,
    *,
    media_type: str,
    route: dict[str, Any],
    asset_ids: list[str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Run the old orchestration API against the approved package generation plan."""
    project_dir = Path(project_dir)
    _synchronize_generation_contract(project_dir)
    plan_path = project_dir / "05_master_assets/master_assets.json"
    if media_type == "video" and plan_path.exists() and not route.get("duration_seconds"):
        plan = load_model(plan_path, MasterAssetPlan)
        route = dict(route)
        route["duration_seconds"] = plan.strategy.source_video_duration_seconds
    report = _ORIGINAL_GENERATE_PROJECT_MEDIA(
        project_dir,
        media_type=media_type,
        route=route,
        asset_ids=asset_ids,
        force=force,
    )
    _synchronize_generation_contract(project_dir)
    return report


_base.generate_project_media = generate_project_media
