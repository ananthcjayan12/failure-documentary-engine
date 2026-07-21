from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Sequence

from .io import safe_copy, write_json
from .models import MasterAssetPlan, ReviewStatus
from .io import load_model


def has_command(name: str) -> bool:
    return shutil.which(name) is not None


def run_command(args: Sequence[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(list(args), cwd=cwd, text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(args)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return completed


def probe_video(path: Path) -> dict:
    if not has_command("ffprobe"):
        return {"path": str(path), "warning": "ffprobe not installed"}
    result = run_command([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=width,height,r_frame_rate,codec_type",
        "-of", "json", str(path),
    ])
    return json.loads(result.stdout)


def _asset_id(name: str) -> str | None:
    import re
    match = re.match(r"(A\d{2,3})", name.upper())
    return match.group(1) if match else None


def import_videos(project_dir: Path, expected_duration: float = 5, tolerance: float = 1.5) -> dict:
    plan_path = project_dir / "05_master_assets/master_assets.json"
    plan = load_model(plan_path, MasterAssetPlan)
    assets = {a.asset_id: a for a in plan.assets}
    inbox = project_dir / "10_generated_videos/inbox"
    approved = project_dir / "10_generated_videos/approved"
    rejected = project_dir / "10_generated_videos/rejected"
    report = {"imported": [], "rejected": [], "warnings": []}
    for source in sorted(inbox.iterdir()):
        if not source.is_file():
            continue
        asset_id = _asset_id(source.name)
        if asset_id not in assets:
            report["rejected"].append({"file": source.name, "reason": "unknown asset ID"})
            continue
        try:
            metadata = probe_video(source)
            if "warning" not in metadata:
                duration = float(metadata.get("format", {}).get("duration", 0))
                streams = metadata.get("streams", [])
                video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
                if not video_stream:
                    raise ValueError("no video stream")
                width, height = int(video_stream["width"]), int(video_stream["height"])
                if height <= 0 or abs(width / height - 16 / 9) > 0.10:
                    raise ValueError("video is not close to 16:9")
                if abs(duration - expected_duration) > tolerance:
                    report["warnings"].append({"file": source.name, "warning": f"duration {duration:.2f}s"})
            else:
                report["warnings"].append({"file": source.name, "warning": metadata["warning"]})
            asset = assets[asset_id]
            asset.video_version += 1
            suffix = source.suffix.lower() if source.suffix else ".mp4"
            destination = approved / f"{asset_id}_master_v{asset.video_version:02d}{suffix}"
            safe_copy(source, destination)
            source.unlink()
            asset.approved_video = str(destination.relative_to(project_dir))
            asset.video_review.status = ReviewStatus.PENDING
            report["imported"].append(str(destination.relative_to(project_dir)))
        except Exception as exc:
            safe_copy(source, rejected / source.name)
            source.unlink(missing_ok=True)
            report["rejected"].append({"file": source.name, "reason": str(exc)})
    write_json(plan_path, plan)
    write_json(project_dir / "10_generated_videos/import_report.json", report)
    return report


def create_variants(project_dir: Path) -> dict:
    plan = load_model(project_dir / "05_master_assets/master_assets.json", MasterAssetPlan)
    out = project_dir / "10_generated_videos/variants"
    out.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, list[dict]] = {"assets": []}
    for asset in plan.assets:
        if not asset.approved_video:
            continue
        source = project_dir / asset.approved_video
        item = {"asset_id": asset.asset_id, "variants": []}
        if not has_command("ffmpeg"):
            destination = out / f"{asset.asset_id}_master{source.suffix}"
            safe_copy(source, destination)
            item["variants"].append({"name": "master", "path": str(destination.relative_to(project_dir))})
            manifest["assets"].append(item)
            continue
        specs = [
            ("full_5s", ["-t", "5"]),
            ("slow_8s", ["-vf", "setpts=1.6*PTS", "-an", "-t", "8"]),
            ("background_10s", ["-stream_loop", "-1", "-vf", "scale=1280:720,boxblur=8:2", "-an", "-t", "10"]),
        ]
        for name, options in specs:
            destination = out / f"{asset.asset_id}_{name}.mp4"
            command = ["ffmpeg", "-y", "-i", str(source), *options, "-r", "24", "-pix_fmt", "yuv420p", str(destination)]
            run_command(command)
            item["variants"].append({"name": name, "path": str(destination.relative_to(project_dir))})
        frame = out / f"{asset.asset_id}_final_frame.png"
        run_command(["ffmpeg", "-y", "-sseof", "-0.1", "-i", str(source), "-frames:v", "1", str(frame)])
        item["variants"].append({"name": "final_frame", "path": str(frame.relative_to(project_dir))})
        manifest["assets"].append(item)
    write_json(out / "variant_manifest.json", manifest)
    return manifest
