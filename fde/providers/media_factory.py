from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from ..assets import import_images
from ..io import load_model, read_json, write_json
from ..media import has_command, import_videos
from ..models import MasterAssetPlan, ReviewStatus
from .gemini_api import generate_image as generate_gemini_image
from .gemini_api import generate_video as generate_gemini_video
from .grok_cli import generate_media as generate_grok_media
from .openai_image_api import generate_image as generate_openai_image


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mock_image(destination: Path, asset_id: str, title: str) -> None:
    image = Image.new("RGB", (1600, 900), "#091522")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 52)
        small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
    except Exception:
        font = ImageFont.load_default()
        small = font
    draw.rounded_rectangle((90, 90, 1510, 810), radius=30, outline="#6ee7c8", width=4)
    draw.text((140, 155), asset_id, font=font, fill="#6ee7c8")
    draw.text((140, 250), title[:70], font=small, fill="#f4f6fb")
    draw.text((140, 680), "OFFLINE MEDIA TEST", font=small, fill="#8d9aaa")
    image.save(destination, "PNG")


def _mock_video(destination: Path, reference: Path | None, duration: float) -> None:
    if not has_command("ffmpeg"):
        raise RuntimeError("FFmpeg is required for mock video generation")
    source = reference
    if source is None or not source.exists():
        placeholder = destination.parent / "mock-reference.png"
        _mock_image(placeholder, "MOCK", "Generated video placeholder")
        source = placeholder
    command = [
        "ffmpeg", "-y", "-loop", "1", "-i", str(source), "-t", f"{duration:.3f}",
        "-vf", "scale=1600:900:force_original_aspect_ratio=increase,crop=1600:900,zoompan=z='min(zoom+0.0005,1.04)':d=1:s=1600x900:fps=24",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(destination),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout)[-3000:])


def _custom_media_command(
    *, template: str, prompt: str, destination: Path, reference: Path | None,
    model: str, duration: float, aspect_ratio: str, quality: str, resolution: str,
    cwd: Path, timeout: int,
) -> dict[str, Any]:
    if not template.strip():
        raise RuntimeError("Custom CLI media command is not configured")
    prompt_path = destination.parent / "prompt.txt"
    prompt_path.write_text(prompt + "\n", encoding="utf-8")
    command = template.format(
        prompt=shlex.quote(str(prompt_path)), output=shlex.quote(str(destination)),
        reference=shlex.quote(str(reference or "")), model=shlex.quote(model),
        duration=shlex.quote(str(duration)), aspect_ratio=shlex.quote(aspect_ratio),
        quality=shlex.quote(quality), resolution=shlex.quote(resolution),
        media_type=shlex.quote("video" if destination.suffix.lower() in {".mp4", ".mov", ".webm"} else "image"),
        cwd=shlex.quote(str(cwd)),
    )
    result = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True, timeout=max(1, timeout))
    (destination.parent / "custom-cli-output.log").write_text(
        (result.stdout or "") + "\n" + (result.stderr or ""), encoding="utf-8"
    )
    if result.returncode != 0:
        raise RuntimeError(f"Custom media command failed ({result.returncode}): {(result.stderr or result.stdout)[-3000:]}")
    if not destination.exists():
        raise RuntimeError("Custom media command completed without creating the configured output path")
    return {
        "provider": "custom_cli", "model": model, "quality": quality,
        "resolution": resolution, "aspect_ratio": aspect_ratio, "path": str(destination),
    }


def generate_one(
    *, provider: str, model: str, prompt: str, destination: Path, media_type: str,
    cwd: Path, reference: Path | None, duration: float, timeout: int,
    media_command_template: str = "", quality: str = "", resolution: str = "",
    aspect_ratio: str = "16:9",
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if provider == "grok_cli":
        return generate_grok_media(
            prompt=prompt, destination=destination, media_type=media_type, cwd=cwd,
            reference=reference, model=model, timeout=timeout, duration=duration,
            aspect_ratio=aspect_ratio, resolution=resolution, quality=quality,
        )
    if provider == "gemini_api":
        if media_type == "image":
            return generate_gemini_image(
                prompt=prompt, destination=destination, model=model,
                resolution=resolution or "2K", aspect_ratio=aspect_ratio, quality=quality or "standard",
                timeout=timeout,
            )
        return generate_gemini_video(
            prompt=prompt, destination=destination, model=model, reference=reference,
            resolution=resolution or "720p", aspect_ratio=aspect_ratio,
            duration=duration, timeout=timeout,
        )
    if provider == "openai_image_api":
        if media_type != "image":
            raise RuntimeError("OpenAI GPT Image provider supports image generation only")
        return generate_openai_image(
            prompt=prompt, destination=destination, model=model,
            resolution=resolution or "1536x1024", quality=quality or "high", timeout=timeout,
        )
    if provider == "custom_cli":
        return _custom_media_command(
            template=media_command_template, prompt=prompt, destination=destination,
            reference=reference, model=model, duration=duration, aspect_ratio=aspect_ratio,
            quality=quality, resolution=resolution, cwd=cwd, timeout=timeout,
        )
    if provider == "mock":
        if media_type == "image":
            _mock_image(destination, destination.parent.parent.name, prompt.splitlines()[0][:70])
        else:
            _mock_video(destination, reference, duration)
        return {
            "provider": "mock", "model": model, "quality": quality,
            "resolution": resolution, "aspect_ratio": aspect_ratio, "path": str(destination),
        }
    if provider in {"manual_upload"}:
        raise RuntimeError(f"{provider} is a manual handoff provider")
    raise RuntimeError(f"Provider {provider} has no native {media_type} adapter")


def generate_project_media(
    project_dir: Path,
    *,
    media_type: str,
    route: dict[str, Any],
    asset_ids: list[str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    if media_type not in {"image", "video"}:
        raise ValueError("media_type must be image or video")
    plan_path = project_dir / "05_master_assets/master_assets.json"
    plan = load_model(plan_path, MasterAssetPlan)
    wanted = set(asset_ids or [])
    root = project_dir / ("08_generated_images" if media_type == "image" else "10_generated_videos")
    generation_root = root / "generation"
    state_path = root / "generation_state.json"
    state = read_json(state_path) if state_path.exists() else {"media_type": media_type, "assets": {}}
    report: dict[str, Any] = {
        "media_type": media_type,
        "provider": route.get("provider"),
        "model": route.get("model"),
        "quality": route.get("quality", ""),
        "resolution": route.get("resolution", ""),
        "aspect_ratio": route.get("aspect_ratio", "16:9"),
        "generated": [], "skipped": [], "failed": [], "manual_required": [],
    }
    retries = max(0, int(route.get("retry_count", 0)))
    timeout = max(1, int(route.get("timeout_seconds") or 3600))
    quality = str(route.get("quality") or "")
    resolution = str(route.get("resolution") or "")
    aspect_ratio = str(route.get("aspect_ratio") or "16:9")
    for asset in plan.assets:
        if wanted and asset.asset_id not in wanted:
            continue
        existing = asset.approved_image if media_type == "image" else asset.approved_video
        review = asset.image_review if media_type == "image" else asset.video_review
        if existing and not force and review.status not in {ReviewStatus.CHANGE_REQUESTED, ReviewStatus.REJECTED}:
            report["skipped"].append({"asset_id": asset.asset_id, "reason": "existing candidate preserved"})
            continue
        if media_type == "video" and not asset.approved_image:
            report["failed"].append({"asset_id": asset.asset_id, "error": "approved image is required"})
            continue
        version = (asset.image_version if media_type == "image" else asset.video_version) + 1
        version_dir = generation_root / asset.asset_id / f"v{version:02d}"
        extension = ".png" if media_type == "image" else ".mp4"
        generated_path = version_dir / f"{asset.asset_id}_generated{extension}"
        reference = project_dir / asset.approved_image if media_type == "video" and asset.approved_image else None
        prompt = asset.image_prompt if media_type == "image" else asset.video_prompt
        duration = 0 if media_type == "image" else float(route.get("duration_seconds") or os.getenv("FDE_MEDIA_DURATION", "5"))
        attempts: list[dict[str, Any]] = []
        candidates = [(
            str(route.get("provider")), str(route.get("model", "")),
            str(route.get("media_command_template", "")), retries + 1,
        )]
        fallback = str(route.get("fallback_provider") or "")
        if fallback and fallback != route.get("provider"):
            candidates.append((
                fallback, str(route.get("fallback_model") or route.get("model") or ""),
                str(route.get("fallback_media_command_template", "")), 1,
            ))
        success = False
        manual = False
        last_error = ""
        for provider_id, selected_model, media_template, count in candidates:
            for attempt in range(1, count + 1):
                try:
                    record = generate_one(
                        provider=provider_id, model=selected_model, prompt=prompt,
                        destination=generated_path, media_type=media_type, cwd=project_dir,
                        reference=reference, duration=duration, timeout=timeout,
                        media_command_template=media_template, quality=quality,
                        resolution=resolution, aspect_ratio=aspect_ratio,
                    )
                    attempts.append({"provider": provider_id, "model": selected_model, "attempt": attempt, "status": "complete"})
                    write_json(version_dir / "generation.json", {
                        **record, "asset_id": asset.asset_id, "media_type": media_type,
                        "prompt": prompt, "reference": str(reference) if reference else None,
                        "quality": quality, "resolution": resolution, "aspect_ratio": aspect_ratio,
                        "duration_seconds": duration, "created_at": utc_now(), "attempts": attempts,
                    })
                    inbox = root / "inbox"
                    inbox.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(generated_path, inbox / f"{asset.asset_id}_generated_v{version:02d}{extension}")
                    success = True
                    break
                except Exception as exc:
                    last_error = str(exc)
                    attempts.append({"provider": provider_id, "model": selected_model, "attempt": attempt, "status": "failed", "error": last_error})
                    if provider_id == "manual_upload":
                        manual = True
                        break
            if success or manual:
                break
        item_state = {
            "asset_id": asset.asset_id, "version": version,
            "status": "generated" if success else "manual_required" if manual else "failed",
            "updated_at": utc_now(), "attempts": attempts,
            "output": str(generated_path.relative_to(project_dir)) if success else None,
            "error": None if success else last_error,
        }
        state["assets"][asset.asset_id] = item_state
        write_json(state_path, state)
        if success:
            report["generated"].append(item_state)
        elif manual:
            report["manual_required"].append(item_state)
        else:
            report["failed"].append(item_state)
    if report["generated"]:
        imported = import_images(project_dir) if media_type == "image" else import_videos(project_dir, float(route.get("duration_seconds") or os.getenv("FDE_MEDIA_DURATION", "5")))
        report["import"] = imported
    write_json(root / "generation_report.json", report)
    return report
