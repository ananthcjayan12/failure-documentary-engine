from __future__ import annotations

import re
from pathlib import Path

from PIL import Image

from .constants import DEFAULT_GLOBAL_STYLE
from .io import load_model, safe_copy, write_json
from .master_footage import approved_master_plan
from .models import MasterAsset, MasterAssetPlan, ReviewStatus, ShotPlan


def _shared_constraints(asset: MasterAsset) -> str:
    return (
        f"Factual scope: {', '.join(asset.factual_scope) or 'visual context only; no new factual claim'}.\n"
        f"Continuity requirements: {', '.join(asset.continuity_requirements) or 'preserve approved project continuity'}.\n"
        f"Subject identity requirements: {', '.join(asset.subject_identity_requirements) or 'preserve approved subject identity'}.\n"
        f"Subject geometry requirements: {', '.join(asset.subject_geometry_requirements) or 'physically credible geometry and scale'}.\n"
        f"Prohibited details: {', '.join(asset.prohibited_details) or 'embedded text, watermark, unsupported action'}.\n"
        f"Overlay-safe zones: {', '.join(asset.overlay_safe_zones) or 'upper right'}.\n"
        f"Useful crop regions: "
        + "; ".join(f"{item.crop_id}: {item.description}" for item in asset.crop_regions)
        + "."
    )


def _hero_prompts(asset: MasterAsset) -> tuple[str, str]:
    image = (
        f"{DEFAULT_GLOBAL_STYLE}\n\n"
        f"HERO FOOTAGE PACKAGE {asset.asset_id}: {asset.title}.\n"
        f"Primary story moment: {asset.primary_use}.\n"
        "Show one clearly defined physical event with accurate subject identity, scale, environment, "
        "and cinematic camera position. Build a strong wide composition plus stable secondary detail "
        "regions for callbacks. Do not add unsupported dramatic action, damage, weather, people, or evidence.\n"
        f"{_shared_constraints(asset)}"
    )
    video = (
        f"Create a single continuous {asset.source_duration_seconds:g}-second hero clip from the approved image. "
        "Preserve identity, geometry, scale, lighting, weather, and every factual boundary. Use realistic physical "
        "movement and restrained cinematic camera motion. Keep opening and ending frames stable enough for callbacks "
        "and match cuts. No internal cuts, morphing, new objects, embedded text, or exaggerated disaster action."
    )
    return image, video


def _atmosphere_prompts(asset: MasterAsset) -> tuple[str, str]:
    image = (
        f"{DEFAULT_GLOBAL_STYLE}\n\n"
        f"LOOPABLE ATMOSPHERE PACKAGE {asset.asset_id}: {asset.title}.\n"
        f"Primary editorial use: {asset.primary_use}.\n"
        "Design a stationary or nearly stationary 16:9 environment with periodic natural movement, large overlay-safe "
        "negative space, and no dominant one-time event. The composition must support practical looping, slowing, "
        "freezing, crops, and technical overlays without appearing repetitive.\n"
        f"{_shared_constraints(asset)}"
    )
    video = (
        f"Create a seamless {asset.source_duration_seconds:g}-second atmosphere loop from the approved image. "
        "Use only periodic natural movement. The first and final frames must match closely in composition, lighting, "
        "object position, and motion phase. Camera must remain stationary or nearly stationary. No unique event, "
        "new object, text, sudden movement, deformation, or non-loopable reveal."
    )
    return image, video


def _investigation_prompts(asset: MasterAsset) -> tuple[str, str]:
    disclosure = (
        asset.reconstruction_disclosure.text
        if asset.reconstruction_disclosure and asset.reconstruction_disclosure.required
        else "no disclosure required"
    )
    image = (
        f"{DEFAULT_GLOBAL_STYLE}\n\n"
        f"INVESTIGATION / RECONSTRUCTION PACKAGE {asset.asset_id}: {asset.title}.\n"
        f"Primary evidence use: {asset.primary_use}.\n"
        f"Factual context ID: {asset.factual_context_id}. Reconstruction disclosure: {disclosure}.\n"
        "Create a controlled technical or investigative environment with multiple useful detail regions, obscured or "
        "non-identifiable people where necessary, replaceable monitor surfaces, accurate instruments and restrained "
        "lighting. Do not bake maps, labels, transcripts, timestamps, radar tracks, or conclusions into the image; "
        "those are deterministic overlay tracks.\n"
        f"{_shared_constraints(asset)}"
    )
    video = (
        f"Create a single continuous {asset.source_duration_seconds:g}-second investigation clip from the approved image. "
        "Preserve all equipment, geometry, identities, monitor surfaces, lighting, and factual boundaries. Use subtle "
        "camera or human movement only. Keep monitor content neutral and replaceable. Do not add readable evidence, "
        "labels, maps, radar tracks, conclusions, or unsupported people. Maintain stable detail regions for overlays."
    )
    return image, video


def prompts_for_asset(asset: MasterAsset) -> tuple[str, str]:
    if asset.category == "hero":
        return _hero_prompts(asset)
    if asset.category == "atmosphere":
        return _atmosphere_prompts(asset)
    if asset.category == "investigation":
        return _investigation_prompts(asset)
    # Legacy compatibility only.
    return _hero_prompts(asset)


def generate_image_prompts(
    plan: MasterAssetPlan,
    shot_plan: ShotPlan | None = None,
) -> MasterAssetPlan:
    """Create a derived generation plan after the package specification is approved.

    `shot_plan` remains an optional compatibility argument. Prompts are generated from
    the approved master-package contract, not independent per-shot directions.
    """
    del shot_plan
    if plan.status not in {"approved", "legacy"}:
        raise RuntimeError("master-footage prompts can only be derived after plan approval")
    derived = plan.model_copy(deep=True)
    for asset in derived.assets:
        asset.image_prompt, asset.video_prompt = prompts_for_asset(asset)
    return derived


def build_generation_plan(project_dir: Path) -> MasterAssetPlan:
    project_dir = Path(project_dir)
    approved = approved_master_plan(project_dir)
    derived = generate_image_prompts(approved)
    write_json(project_dir / "05_master_assets/generation_plan.json", derived)
    for asset in derived.assets:
        prompt_dir = project_dir / "05_master_assets/prompts" / asset.asset_id
        prompt_dir.mkdir(parents=True, exist_ok=True)
        (prompt_dir / "image_prompt.txt").write_text(asset.image_prompt.rstrip() + "\n", encoding="utf-8")
        (prompt_dir / "video_prompt.txt").write_text(asset.video_prompt.rstrip() + "\n", encoding="utf-8")
    return derived


def _asset_id_from_name(name: str) -> str | None:
    match = re.match(r"([HLE]\d{2,3}|A\d{2,3})", name.upper())
    return match.group(1) if match else None


def import_images(project_dir: Path, min_width: int = 1280, ratio_tolerance: float = 0.08) -> dict:
    generation_path = project_dir / "05_master_assets/generation_plan.json"
    plan_path = generation_path if generation_path.exists() else project_dir / "05_master_assets/master_assets.json"
    plan = load_model(plan_path, MasterAssetPlan)
    assets = {item.asset_id: item for item in plan.assets}
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
