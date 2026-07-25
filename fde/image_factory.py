from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from PIL import Image

from .assets import generate_image_prompts, import_images
from .constants import DEFAULT_GLOBAL_STYLE
from .io import load_model, write_json
from .models import DocumentaryScript, MasterAsset, MasterAssetPlan, ProjectBrief, ShotSkeletonPlan

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
FACTORY_SCHEMA_VERSION = "1.0"


def _slug(text: str, max_length: int = 48) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return value[:max_length].rstrip("_") or "asset"


def _asset_narration(asset: MasterAsset, skeleton: ShotSkeletonPlan, script: DocumentaryScript) -> dict[str, Any]:
    shots = {shot.shot_id: shot for shot in skeleton.shots}
    narration = {segment.narration_id: segment for segment in script.segments}
    linked = [shots[shot_id] for shot_id in asset.linked_shots if shot_id in shots]
    narration_ids = list(dict.fromkeys(nid for shot in linked for nid in shot.narration_ids))
    text = " ".join(narration[nid].text for nid in narration_ids if nid in narration)
    start = min((shot.start for shot in linked), default=0.0)
    end = max((shot.start + shot.duration for shot in linked), default=start)
    motions = sorted({shot.story_function for shot in linked if shot.story_function})
    return {
        "narration_ids": narration_ids,
        "narration_text": text,
        "start_seconds": round(start, 2),
        "end_seconds": round(end, 2),
        "motion_options": motions,
        "overlay_requirements": [],
    }


def _select_anchors(assets: list[MasterAsset], maximum: int = 5) -> set[str]:
    by_category: dict[str, list[MasterAsset]] = defaultdict(list)
    for asset in assets:
        by_category[asset.category].append(asset)
    anchors: list[MasterAsset] = []
    for category in ["hero", "investigation", "atmosphere", "story_specific"]:
        candidates = by_category.get(category, [])
        if candidates:
            anchors.append(max(candidates, key=lambda item: item.required_reuse_count))
    remaining = sorted(
        [asset for asset in assets if asset not in anchors],
        key=lambda item: item.required_reuse_count,
        reverse=True,
    )
    anchors.extend(remaining[: max(0, maximum - len(anchors))])
    return {asset.asset_id for asset in anchors[:maximum]}


def _reference_map(assets: list[MasterAsset], anchors: set[str]) -> dict[str, str]:
    category_anchor: dict[str, str] = {}
    for asset in assets:
        if asset.asset_id in anchors and asset.category not in category_anchor:
            category_anchor[asset.category] = asset.asset_id
    fallback = next(iter(anchors), "")
    return {
        asset.asset_id: (asset.asset_id if asset.asset_id in anchors else category_anchor.get(asset.category, fallback))
        for asset in assets
    }


def _acceptance_checks(asset: MasterAsset) -> list[str]:
    checks = [
        "One clean 16:9 landscape image with no collage or split screen",
        "No embedded text, subtitles, labels, watermarks, borders, or logos",
        "Photorealistic, technically credible geometry and scale",
        "Composition contains useful negative space for later overlays",
        "Image has a stable subject and clear movement opportunity for image-to-video",
        "No gratuitous suffering, sensational explosion, or fantasy lighting",
    ]
    if asset.category == "hero":
        checks.extend([
            "Primary vehicle or structure has no duplicated or malformed components",
            "Wide frame and at least one useful detail crop are available",
        ])
    elif asset.category == "investigation":
        checks.extend([
            "Equipment looks contemporary and plausible rather than futuristic",
            "Screens remain abstract or blank so accurate graphics can be added later",
        ])
    elif asset.category == "atmosphere":
        checks.extend([
            "Camera is locked or nearly locked",
            "Environmental motion can loop without a visible one-time event",
        ])
    else:
        checks.append("Story-specific evidence remains neutral and does not imply an unproven conclusion")
    return checks


def _complete_prompt(asset: MasterAsset, info: dict[str, Any], anchor_id: str) -> str:
    continuity = (
        f"Use approved asset {anchor_id} as the visual continuity reference for this family. "
        "Preserve its color science, realism, material treatment, lighting language, and camera discipline."
        if anchor_id and anchor_id != asset.asset_id
        else "This is a continuity-anchor image. Establish a reusable visual identity for its asset family."
    )
    motion = "; ".join(info["motion_options"][:3]) or "subtle controlled environmental movement"
    return (
        f"ASSET ID: {asset.asset_id}\n"
        f"ASSET TITLE: {asset.title}\n"
        f"ASSET FAMILY: {asset.category}\n\n"
        f"CONTINUITY:\n{continuity}\n\n"
        f"NARRATIVE PURPOSE:\n{asset.primary_use}\n\n"
        f"SCENE REQUEST:\n{asset.image_prompt}\n\n"
        f"ANIMATION INTENTION:\nThis still will later become a five-second video. "
        f"Compose it so the following movement can occur naturally: {motion}.\n\n"
        "OUTPUT CONTRACT:\n"
        "Generate exactly one landscape production image. Use a true cinematic 16:9 composition or the closest "
        "available landscape canvas while keeping all critical subjects inside the central 80% safe area. "
        "Do not render the asset ID or any other text inside the image. Begin from the supplied continuity reference "
        "when one is attached. Preserve successful visual continuity across the family."
    )


def export_image_factory_packet(project_dir: Path, output_dir: Path | None = None) -> dict[str, str]:
    """Create a compact upload packet for the Documentary Image Factory custom GPT."""
    brief = load_model(project_dir / "00_input/project_brief.json", ProjectBrief)
    plan_path = project_dir / "05_master_assets/master_assets.json"
    plan = load_model(plan_path, MasterAssetPlan)
    skeleton = load_model(project_dir / "06_shots/shot_skeleton.json", ShotSkeletonPlan)
    script = load_model(project_dir / "03_narration/narration.json", DocumentaryScript)

    if any(not asset.image_prompt for asset in plan.assets):
        plan = generate_image_prompts(plan)
        write_json(plan_path, plan)

    packet_dir = output_dir or project_dir / "07_review/image_factory_packet"
    if packet_dir.exists():
        shutil.rmtree(packet_dir)
    packet_dir.mkdir(parents=True, exist_ok=True)

    anchors = _select_anchors(plan.assets)
    references = _reference_map(plan.assets, anchors)
    ranked = sorted(
        plan.assets,
        key=lambda item: (item.asset_id not in anchors, -item.required_reuse_count, item.asset_id),
    )
    essential_ids = {asset.asset_id for asset in ranked[: min(18, len(ranked))]}

    manifest_assets: list[dict[str, Any]] = []
    for asset in plan.assets:
        info = _asset_narration(asset, skeleton, script)
        expected_filename = f"{asset.asset_id}_{_slug(asset.title)}_v01.png"
        manifest_assets.append({
            "asset_id": asset.asset_id,
            "title": asset.title,
            "family": asset.category,
            "priority": "essential" if asset.asset_id in essential_ids else "enhancement",
            "is_continuity_anchor": asset.asset_id in anchors,
            "continuity_reference_asset_id": references.get(asset.asset_id, ""),
            "linked_shots": asset.linked_shots,
            "primary_use": asset.primary_use,
            "secondary_uses": asset.secondary_uses,
            "planned_reuse_count": asset.required_reuse_count,
            **info,
            "expected_filename": expected_filename,
            "acceptance_checks": _acceptance_checks(asset),
            "complete_prompt": _complete_prompt(asset, info, references.get(asset.asset_id, "")),
            "status": "pending",
            "version": 0,
            "qc": None,
        })

    batches: list[dict[str, Any]] = []
    anchor_assets = [item for item in manifest_assets if item["is_continuity_anchor"]]
    if anchor_assets:
        batches.append({"batch_id": "B00_ANCHORS", "asset_ids": [item["asset_id"] for item in anchor_assets]})
    for family in ["hero", "investigation", "atmosphere", "story_specific"]:
        members = [
            item["asset_id"] for item in manifest_assets
            if item["family"] == family and not item["is_continuity_anchor"]
        ]
        for start in range(0, len(members), 6):
            chunk = members[start:start + 6]
            if chunk:
                batches.append({
                    "batch_id": f"B{len(batches):02d}_{family.upper()}",
                    "asset_ids": chunk,
                })

    manifest = {
        "schema_version": FACTORY_SCHEMA_VERSION,
        "project": brief.model_dump(mode="json"),
        "global_style": DEFAULT_GLOBAL_STYLE,
        "factory_contract": {
            "asset_count": len(manifest_assets),
            "maximum_retry_per_asset": 1,
            "generate_one_image_per_asset": True,
            "never_regenerate_passed_assets": True,
            "target_aspect_ratio": "16:9",
            "packaging_filename": f"{brief.project_id}_images_approved.zip",
        },
        "batches": batches,
        "assets": manifest_assets,
    }
    write_json(packet_dir / "ASSET_MANIFEST.json", manifest)
    write_json(packet_dir / "IMAGE_FACTORY_STATE.json", {
        "schema_version": FACTORY_SCHEMA_VERSION,
        "project_id": brief.project_id,
        "completed_asset_ids": [],
        "pending_asset_ids": [item["asset_id"] for item in manifest_assets],
        "review_required_asset_ids": [],
        "current_batch_id": batches[0]["batch_id"] if batches else None,
    })
    write_json(packet_dir / "BATCH_PLAN.json", {"project_id": brief.project_id, "batches": batches})

    packet_md = [
        f"# {brief.title} — Documentary Image Production Packet",
        "",
        f"**Project ID:** `{brief.project_id}`  ",
        f"**Final assets:** {len(manifest_assets)}  ",
        f"**Target duration:** {brief.target_duration_seconds:.0f} seconds  ",
        "",
        "The JSON manifest is the source of truth. Generate actual images; do not merely rewrite the prompts.",
        "",
    ]
    for item in manifest_assets:
        packet_md.extend([
            f"## {item['asset_id']} — {item['title']}",
            "",
            f"- Family: `{item['family']}`",
            f"- Priority: `{item['priority']}`",
            f"- Continuity anchor: `{item['is_continuity_anchor']}`",
            f"- Reference: `{item['continuity_reference_asset_id']}`",
            f"- Expected filename: `{item['expected_filename']}`",
            f"- Narration coverage: {item['start_seconds']:.1f}s–{item['end_seconds']:.1f}s",
            "",
            "### Narration",
            item["narration_text"] or item["primary_use"],
            "",
            "### Production prompt",
            "```text",
            item["complete_prompt"],
            "```",
            "",
            "### Acceptance checks",
            *[f"- [ ] {check}" for check in item["acceptance_checks"]],
            "",
        ])
    (packet_dir / "PRODUCTION_PACKET.md").write_text("\n".join(packet_md), encoding="utf-8")

    run_instructions = f"""# Run Instructions — {brief.title}

Upload all files from this folder into one conversation with the private **Documentary Image Factory** GPT.
Then send this exact command:

```text
RUN PRODUCTION PACKET

Read ASSET_MANIFEST.json and IMAGE_FACTORY_STATE.json as the source of truth.
Generate the actual {len(manifest_assets)} production images in BATCH_PLAN.json order.
Start with B00_ANCHORS, validate them, and use each approved anchor as the continuity reference for its family.
For every asset: generate one image, inspect it against acceptance_checks, retry at most once only if it clearly fails, and never regenerate a passed asset.
Do not ask me to approve individual images. Maintain IMAGE_FACTORY_STATE.json after every batch.
At completion, create the contact sheet, QC report, completed manifest, and `{brief.project_id}_images_approved.zip` using the exact filenames from the manifest.
If a platform generation limit stops the run, preserve completed assets and respond only with the exact resume command needed for the first pending batch.
```

Expected output ZIP layout:

```text
{brief.project_id}_images_approved.zip
├── images/
├── contact_sheet/
├── reports/
└── manifest/
```
"""
    (packet_dir / "RUN_INSTRUCTIONS.md").write_text(run_instructions, encoding="utf-8")

    upload_readme = """# Files to upload to the Custom GPT conversation

Upload these four files together:

1. `ASSET_MANIFEST.json`
2. `IMAGE_FACTORY_STATE.json`
3. `BATCH_PLAN.json`
4. `PRODUCTION_PACKET.md`

`RUN_INSTRUCTIONS.md` contains the one command to paste after upload.
The JSON files are authoritative; the Markdown file exists for easy human review.
"""
    (packet_dir / "UPLOAD_README.md").write_text(upload_readme, encoding="utf-8")

    zip_path = packet_dir.parent / f"{brief.project_id}_image_factory_packet.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(packet_dir.rglob("*")):
            if file.is_file():
                archive.write(file, file.relative_to(packet_dir))
    return {
        "packet_directory": str(packet_dir),
        "packet_zip": str(zip_path),
        "asset_count": str(len(manifest_assets)),
        "batch_count": str(len(batches)),
    }


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    root = destination.resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if root not in target.parents and target != root:
            raise ValueError(f"unsafe ZIP path: {member.filename}")
    archive.extractall(destination)


def _normalize_landscape(source: Path, destination: Path, width: int = 1600, height: int = 900) -> None:
    """Normalize UI-generated landscape images to a clean 16:9 PNG."""
    with Image.open(source) as opened:
        image = opened.convert("RGB")
        source_ratio = image.width / image.height
        target_ratio = width / height
        if source_ratio > target_ratio:
            crop_width = int(image.height * target_ratio)
            left = max(0, (image.width - crop_width) // 2)
            image = image.crop((left, 0, left + crop_width, image.height))
        elif source_ratio < target_ratio:
            crop_height = int(image.width / target_ratio)
            top = max(0, (image.height - crop_height) // 2)
            image = image.crop((0, top, image.width, top + crop_height))
        image = image.resize((width, height), Image.Resampling.LANCZOS)
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination, "PNG", optimize=True)


def import_image_factory_batch(project_dir: Path, batch_zip: Path, min_width: int = 1280) -> dict[str, Any]:
    """Import a ZIP returned by the Custom GPT, normalize images, then run normal validation."""
    if not batch_zip.exists():
        raise FileNotFoundError(batch_zip)
    inbox = project_dir / "08_generated_images/inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    skipped: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="fde-image-factory-") as temp:
        temp_dir = Path(temp)
        with zipfile.ZipFile(batch_zip) as archive:
            _safe_extract(archive, temp_dir)
        for source in sorted(temp_dir.rglob("*")):
            if not source.is_file() or source.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            match = re.match(r"([HLE]\d{2,3})", source.name.upper())
            if not match:
                skipped.append({"file": source.name, "reason": "filename does not start with an H##, L##, or E## asset ID"})
                continue
            asset_id = match.group(1)
            destination = inbox / f"{asset_id}_{_slug(source.stem)}.png"
            try:
                _normalize_landscape(source, destination)
                copied.append(str(destination.relative_to(project_dir)))
            except Exception as exc:
                skipped.append({"file": source.name, "reason": str(exc)})
    validation = import_images(project_dir, min_width=min_width, ratio_tolerance=0.01)
    report = {"copied_to_inbox": copied, "skipped": skipped, "validation": validation}
    write_json(project_dir / "08_generated_images/image_factory_import_report.json", report)
    return report
