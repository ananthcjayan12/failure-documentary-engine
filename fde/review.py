from __future__ import annotations

from pathlib import Path

from .io import load_model, write_json
from .models import MasterAssetPlan, ReviewStatus, utc_now
from .project import ProjectStore


def review_asset(
    store: ProjectStore,
    project_id: str,
    asset_id: str,
    status: ReviewStatus,
    instruction: str = "",
    preserve: list[str] | None = None,
    target: str = "image",
) -> MasterAssetPlan:
    project_dir = store.project_dir(project_id)
    path = project_dir / "05_master_assets/master_assets.json"
    plan = load_model(path, MasterAssetPlan)
    asset = next((a for a in plan.assets if a.asset_id == asset_id), None)
    if not asset:
        raise ValueError(f"unknown asset: {asset_id}")
    review = asset.image_review if target == "image" else asset.video_review
    review.status = status
    review.instruction = instruction
    review.preserve = preserve or []
    review.reviewed_at = utc_now()
    if status != ReviewStatus.APPROVED:
        invalidations = [
            f"asset:{asset_id}:{target}",
            f"video_job:{asset_id}",
            f"variants:{asset_id}",
            *[f"timeline:{shot_id}" for shot_id in asset.linked_shots],
        ]
        if target == "image":
            asset.video_review.status = ReviewStatus.PENDING
            asset.approved_video = None
        store.invalidate(project_id, invalidations)
    else:
        store.clear_invalidation(project_id, [f"asset:{asset_id}:{target}"])
    write_json(path, plan)
    return plan


def approval_summary(project_dir: Path) -> dict:
    plan = load_model(project_dir / "05_master_assets/master_assets.json", MasterAssetPlan)
    return {
        "total": len(plan.assets),
        "images_approved": sum(a.image_review.status == ReviewStatus.APPROVED for a in plan.assets),
        "videos_approved": sum(a.video_review.status == ReviewStatus.APPROVED for a in plan.assets),
        "missing_images": [a.asset_id for a in plan.assets if not a.approved_image],
        "missing_videos": [a.asset_id for a in plan.assets if not a.approved_video],
        "pending_image_reviews": [a.asset_id for a in plan.assets if a.image_review.status != ReviewStatus.APPROVED],
        "pending_video_reviews": [a.asset_id for a in plan.assets if a.video_review.status != ReviewStatus.APPROVED],
        "uncovered_shots": plan.uncovered_shots,
    }
