from __future__ import annotations

import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from .assets import import_images
from .image_factory import IMAGE_EXTENSIONS
from . import image_factory as _base
from .io import load_model, write_json
from .models import MasterAssetPlan


def _synchronize_master_media(project_dir: Path) -> None:
    generation_path = project_dir / "05_master_assets/generation_plan.json"
    master_path = project_dir / "05_master_assets/master_assets.json"
    if not generation_path.exists() or not master_path.exists():
        return
    generated = load_model(generation_path, MasterAssetPlan)
    master = load_model(master_path, MasterAssetPlan)
    generated_by_id = {item.asset_id: item for item in generated.assets}
    for asset in master.assets:
        source = generated_by_id.get(asset.asset_id)
        if source is None:
            continue
        asset.image_prompt = source.image_prompt
        asset.video_prompt = source.video_prompt
        asset.approved_image = source.approved_image
        asset.image_version = source.image_version
        asset.image_review = source.image_review
        if source.approved_video:
            asset.approved_video = source.approved_video
            asset.video_version = source.video_version
            asset.video_review = source.video_review
    write_json(master_path, master)


def import_image_factory_batch(
    project_dir: Path,
    batch_zip: Path,
    min_width: int = 1280,
) -> dict[str, Any]:
    """Import H/L/E package filenames while preserving A## legacy archives."""
    project_dir = Path(project_dir)
    batch_zip = Path(batch_zip)
    if not batch_zip.exists():
        raise FileNotFoundError(batch_zip)
    inbox = project_dir / "08_generated_images/inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    skipped: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="fde-image-factory-") as temp:
        temp_dir = Path(temp)
        with zipfile.ZipFile(batch_zip) as archive:
            _base._safe_extract(archive, temp_dir)
        for source in sorted(temp_dir.rglob("*")):
            if not source.is_file() or source.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            match = re.match(r"([HLEA]\d{2,3})", source.name.upper())
            if not match:
                skipped.append(
                    {
                        "file": source.name,
                        "reason": "filename does not start with H##, L##, E##, or legacy A##",
                    }
                )
                continue
            asset_id = match.group(1)
            destination = inbox / f"{asset_id}_{_base._slug(source.stem)}.png"
            try:
                _base._normalize_landscape(source, destination)
                copied.append(str(destination.relative_to(project_dir)))
            except Exception as exc:
                skipped.append({"file": source.name, "reason": str(exc)})
    validation = import_images(
        project_dir,
        min_width=min_width,
        ratio_tolerance=0.01,
    )
    _synchronize_master_media(project_dir)
    report = {
        "copied_to_inbox": copied,
        "skipped": skipped,
        "validation": validation,
    }
    write_json(
        project_dir / "08_generated_images/image_factory_import_report.json",
        report,
    )
    return report


_base.import_image_factory_batch = import_image_factory_batch
