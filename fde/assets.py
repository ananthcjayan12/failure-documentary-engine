from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from PIL import Image

from .constants import DEFAULT_GLOBAL_STYLE
from .io import load_model, safe_copy, write_json
from .models import MasterAssetPlan, ReviewStatus, ShotPlan


def generate_image_prompts(plan: MasterAssetPlan, shot_plan: ShotPlan) -> MasterAssetPlan:
    shots = {shot.shot_id: shot for shot in shot_plan.shots}
    for asset in plan.assets:
        linked = [shots[sid] for sid in asset.linked_shots]
        cameras = sorted({s.camera for s in linked if s.camera})
        motions = sorted({s.motion for s in linked if s.motion})
        overlays = sorted({item for s in linked for item in s.overlay_requirements})
        asset.image_prompt = (
            f"{DEFAULT_GLOBAL_STYLE}\n\n"
            f"MASTER ASSET {asset.asset_id}: {asset.title}.\n"
            f"Primary narrative use: {asset.primary_use}.\n"
            f"Composition: {', '.join(cameras[:3]) or 'stable cinematic wide composition'}.\n"
            f"Future movement: {', '.join(motions[:3]) or 'subtle controlled environmental movement'}.\n"
            f"Leave clean negative space for overlays: {', '.join(overlays[:6]) or 'documentary labels and evidence graphics'}.\n"
            "The image must provide multiple useful crop regions: one strong wide frame, one subject detail, "
            "and one clean atmospheric area. Preserve realistic geometry and continuity."
        )
        asset.video_prompt = (
            "Preserve the approved image composition, subject identity, geometry, lighting, and colour palette. "
            f"Animate only: {', '.join(motions[:3]) or 'subtle natural environmental movement'}. "
            "Single continuous five-second shot, no internal cuts, no camera orbit, no sudden acceleration, "
            "no deformation, no added objects, no text, and stable opening and ending frames."
        )
    return plan


def _asset_id_from_name(name: str) -> str | None:
    match = re.match(r"(A\d{2,3})", name.upper())
    return match.group(1) if match else None


def import_images(project_dir: Path, min_width: int = 1280, ratio_tolerance: float = 0.08) -> dict:
    plan_path = project_dir / "05_master_assets/master_assets.json"
    plan = load_model(plan_path, MasterAssetPlan)
    assets = {a.asset_id: a for a in plan.assets}
    inbox = project_dir / "08_generated_images/inbox"
    approved_dir = project_dir / "08_generated_images/approved"
    thumbnails = project_dir / "08_generated_images/thumbnails"
    results: dict[str, list] = {"imported": [], "rejected": [], "warnings": []}
    for source in sorted(inbox.iterdir()):
        if not source.is_file():
            continue
        asset_id = _asset_id_from_name(source.name)
        if asset_id not in assets:
            results["rejected"].append({"file": source.name, "reason": "unknown asset ID"})
            continue
        try:
            with Image.open(source) as image:
                image.verify()
            with Image.open(source) as image:
                width, height = image.size
                ratio = width / height
                if width < min_width:
                    raise ValueError(f"width {width} below minimum {min_width}")
                if abs(ratio - 16 / 9) > ratio_tolerance:
                    raise ValueError(f"aspect ratio {ratio:.3f} is not close to 16:9")
                image = image.convert("RGB")
                asset = assets[asset_id]
                asset.image_version += 1
                destination = approved_dir / f"{asset_id}_v{asset.image_version:02d}.png"
                image.save(destination, "PNG", optimize=True)
                thumb = image.copy()
                thumb.thumbnail((640, 360))
                thumb.save(thumbnails / f"{asset_id}.jpg", "JPEG", quality=88)
                asset.approved_image = str(destination.relative_to(project_dir))
                asset.image_review.status = ReviewStatus.PENDING
                results["imported"].append(str(destination.relative_to(project_dir)))
            source.unlink()
        except Exception as exc:
            rejected_dir = project_dir / "08_generated_images/rejected"
            rejected_dir.mkdir(parents=True, exist_ok=True)
            safe_copy(source, rejected_dir / source.name)
            source.unlink(missing_ok=True)
            results["rejected"].append({"file": source.name, "reason": str(exc)})
    write_json(plan_path, plan)
    write_json(project_dir / "08_generated_images/import_report.json", results)
    return results
