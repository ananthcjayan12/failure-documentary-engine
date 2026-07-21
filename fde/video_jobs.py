from __future__ import annotations

from pathlib import Path

from .io import load_model, write_json
from .models import MasterAssetPlan, ReviewStatus, VideoJob, VideoJobManifest


def create_video_jobs(project_dir: Path, duration_seconds: float = 5) -> VideoJobManifest:
    plan = load_model(project_dir / "05_master_assets/master_assets.json", MasterAssetPlan)
    jobs: list[VideoJob] = []
    for asset in plan.assets:
        if not asset.approved_image:
            raise ValueError(f"asset {asset.asset_id} has no imported image")
        if asset.image_review.status != ReviewStatus.APPROVED:
            raise ValueError(f"asset {asset.asset_id} image is not approved")
        job = VideoJob(
            video_job_id=f"VJOB_{asset.asset_id}", asset_id=asset.asset_id,
            input_image=asset.approved_image, duration_seconds=duration_seconds,
            prompt=asset.video_prompt,
            expected_filename=f"{asset.asset_id}_master_v01.mp4",
            linked_shots=asset.linked_shots,
        )
        jobs.append(job)
        prompt_path = project_dir / f"09_video_jobs/prompts/{asset.asset_id}_video_prompt.txt"
        prompt_path.write_text(asset.video_prompt + "\n", encoding="utf-8")
    manifest = VideoJobManifest(project_id=plan.project_id, jobs=jobs)
    write_json(project_dir / "09_video_jobs/video_jobs.json", manifest)
    return manifest
