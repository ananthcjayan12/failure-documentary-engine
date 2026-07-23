from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .assets import build_generation_plan
from .io import load_model, write_json
from .master_footage import approved_master_plan
from .models import (
    AnimaticManifest,
    AudioManifest,
    EditorialShot,
    EditorialShotPlan,
    MasterAsset,
    MasterAssetPlan,
    OverlaySpec,
    ProjectState,
    Timeline,
    TimelineEntry,
    V1MediaJob,
    V1MediaManifest,
    utc_now,
)
from .project import ProjectStore
from .providers.media_factory import generate_one
from .timeline import build_timeline


def _route_from_env(media_type: str) -> dict[str, Any]:
    prefix = "FDE_IMAGE" if media_type == "image" else "FDE_VIDEO"
    return {
        "provider": os.getenv(f"{prefix}_PROVIDER") or os.getenv("FDE_MEDIA_PROVIDER", "mock"),
        "model": os.getenv(f"{prefix}_MODEL") or os.getenv("FDE_MEDIA_MODEL", "Deterministic Demo"),
        "timeout": int(float(os.getenv("FDE_MEDIA_TIMEOUT", "3600") or 3600)),
        "command": os.getenv("FDE_MEDIA_COMMAND", ""),
        "quality": os.getenv("FDE_MEDIA_QUALITY", ""),
        "resolution": os.getenv("FDE_MEDIA_RESOLUTION", ""),
        "aspect_ratio": os.getenv("FDE_MEDIA_ASPECT_RATIO", "16:9") or "16:9",
        "duration_seconds": float(os.getenv("FDE_MEDIA_DURATION", "0") or 0),
    }


def _manifest_path(project_dir: Path, media_type: str) -> Path:
    return project_dir / ("07_images/jobs.json" if media_type == "image" else "09_videos/jobs.json")


def _image_path(project_dir: Path, asset_id: str) -> Path:
    return project_dir / "07_images" / asset_id / "image.png"


def _video_path(project_dir: Path, asset_id: str) -> Path:
    return project_dir / "09_videos" / asset_id / "approved.mp4"


def _editorial_plan(project_dir: Path) -> EditorialShotPlan:
    return load_model(project_dir / "06_shots/editorial_shot_plan.json", EditorialShotPlan)


def _generation_plan(project_dir: Path) -> MasterAssetPlan:
    path = project_dir / "05_master_assets/generation_plan.json"
    if path.exists():
        return load_model(path, MasterAssetPlan)
    return build_generation_plan(project_dir)


def _mock_image(destination: Path, asset: MasterAsset) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1600, 900), "#07131f")
    draw = ImageDraw.Draw(image)
    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60)
        body_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
    except Exception:
        title_font = body_font = ImageFont.load_default()
    accent = {
        "hero": "#f1a85b",
        "atmosphere": "#5ed9c5",
        "investigation": "#77a7ff",
    }.get(asset.category, "#5ed9c5")
    draw.rounded_rectangle((72, 72, 1528, 828), radius=28, outline=accent, width=4)
    draw.text((120, 118), f"{asset.asset_id} · {asset.category.upper()}", font=title_font, fill=accent)
    text = asset.title[:150]
    lines = [text[index:index + 66] for index in range(0, len(text), 66)]
    for index, line in enumerate(lines[:3]):
        draw.text((120, 270 + index * 50), line, font=body_font, fill="#edf4f7")
    draw.text(
        (120, 690),
        f"Linked shots: {len(asset.linked_shots)} · Source: {asset.source_duration_seconds:g}s",
        font=body_font,
        fill="#8ea5b1",
    )
    image.save(destination, "PNG")


def prepare_media_jobs(
    project_dir: Path,
    media_type: str,
    route: dict[str, Any] | None = None,
) -> V1MediaManifest:
    """Create exactly one provider job per approved generated master package."""
    if media_type not in {"image", "video"}:
        raise ValueError("media_type must be image or video")
    project_dir = Path(project_dir)
    route = route or _route_from_env(media_type)
    approved = approved_master_plan(project_dir)
    plan = _generation_plan(project_dir)
    if plan.plan_version != approved.plan_version:
        raise RuntimeError("generation plan is stale relative to the approved master-footage plan")
    if len(plan.assets) != plan.strategy.target_generated_video_count:
        raise RuntimeError(
            f"expected {plan.strategy.target_generated_video_count} master packages; "
            f"found {len(plan.assets)}"
        )
    existing_path = _manifest_path(project_dir, media_type)
    existing = load_model(existing_path, V1MediaManifest) if existing_path.exists() else None
    existing_by_id = {
        (item.asset_id or item.shot_id): item for item in existing.jobs
    } if existing else {}
    resolution = str(route.get("resolution") or ("2K" if media_type == "image" else "720p"))
    aspect_ratio = str(route.get("aspect_ratio") or "16:9")
    jobs: list[V1MediaJob] = []
    for asset in plan.assets:
        old = existing_by_id.get(asset.asset_id)
        prompt = asset.image_prompt if media_type == "image" else asset.video_prompt
        output_path = _image_path(project_dir, asset.asset_id) if media_type == "image" else _video_path(project_dir, asset.asset_id)
        output = str(output_path.relative_to(project_dir))
        reference = str(_image_path(project_dir, asset.asset_id).relative_to(project_dir)) if media_type == "video" else None
        duration = 0 if media_type == "image" else asset.source_duration_seconds
        if (
            old
            and old.prompt == prompt
            and old.duration_seconds == duration
            and old.resolution == resolution
            and old.aspect_ratio == aspect_ratio
            and old.category == asset.category
            and old.linked_shots == asset.linked_shots
        ):
            jobs.append(old)
            continue
        jobs.append(
            V1MediaJob(
                job_id=f"{media_type.upper()}_{asset.asset_id}",
                shot_id=asset.asset_id,
                asset_id=asset.asset_id,
                category=asset.category,
                linked_shots=list(asset.linked_shots),
                media_type=media_type,
                status="pending",
                prompt=prompt,
                output=output,
                reference=reference,
                duration_seconds=duration,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
            )
        )
        job_dir = output_path.parent
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "prompt.txt").write_text(prompt.rstrip() + "\n", encoding="utf-8")
        write_json(
            job_dir / "asset_contract.json",
            {
                "asset_id": asset.asset_id,
                "category": asset.category,
                "linked_shots": asset.linked_shots,
                "source_duration_seconds": asset.source_duration_seconds,
                "loopable": asset.loopable,
                "allowed_operations": asset.allowed_operations,
                "crop_regions": [item.model_dump(mode="json") for item in asset.crop_regions],
                "factual_scope": asset.factual_scope,
                "continuity_requirements": asset.continuity_requirements,
            },
        )
    manifest = V1MediaManifest(
        project_id=plan.project_id,
        media_type=media_type,
        jobs=jobs,
    )
    write_json(existing_path, manifest)
    write_json(
        existing_path.parent / "route_snapshot.json",
        {
            "provider": route.get("provider"),
            "model": route.get("model"),
            "quality": route.get("quality"),
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
            "provider_duration_seconds": route.get("duration_seconds", 0),
            "master_plan_version": plan.plan_version,
            "job_count": len(jobs),
            "updated_at": utc_now(),
        },
    )
    return manifest


def _wanted_assets(
    plan: MasterAssetPlan,
    requested: list[str] | None,
) -> set[str]:
    if not requested:
        return set()
    requested_set = {item.upper() for item in requested}
    selected: set[str] = set()
    for asset in plan.assets:
        if asset.asset_id in requested_set or requested_set.intersection(asset.linked_shots):
            selected.add(asset.asset_id)
    unknown = requested_set - selected - {shot for asset in plan.assets for shot in asset.linked_shots}
    if unknown:
        raise ValueError(f"unknown asset or shot ID(s): {', '.join(sorted(unknown))}")
    return selected


def generate_media_jobs(
    project_dir: Path,
    *,
    media_type: str,
    shot_ids: list[str] | None = None,
    force: bool = False,
    route: dict[str, Any] | None = None,
) -> V1MediaManifest:
    project_dir = Path(project_dir)
    route = route or _route_from_env(media_type)
    plan = _generation_plan(project_dir)
    manifest = prepare_media_jobs(project_dir, media_type, route=route)
    wanted = _wanted_assets(plan, shot_ids)
    assets = {item.asset_id: item for item in plan.assets}
    for job in manifest.jobs:
        asset_id = job.asset_id or job.shot_id
        if wanted and asset_id not in wanted:
            continue
        output = project_dir / str(job.output)
        if output.exists() and job.status in {"review", "approved"} and not force:
            continue
        if media_type == "video" and not _image_path(project_dir, asset_id).exists():
            job.status = "failed"
            job.error = "approved master-package image is required before video generation"
            job.updated_at = utc_now()
            write_json(_manifest_path(project_dir, media_type), manifest)
            continue
        job.status = "generating"
        job.error = None
        job.updated_at = utc_now()
        write_json(_manifest_path(project_dir, media_type), manifest)
        try:
            provider = str(route.get("provider", "mock"))
            asset = assets[asset_id]
            if provider == "mock" and media_type == "image":
                _mock_image(output, asset)
                record = {
                    "provider": "mock",
                    "model": route.get("model"),
                    "path": str(output),
                }
            else:
                provider_duration = float(
                    route.get("duration_seconds") or asset.source_duration_seconds
                ) if media_type == "video" else 0
                record = generate_one(
                    provider=provider,
                    model=str(route.get("model", "")),
                    prompt=job.prompt,
                    destination=output,
                    media_type=media_type,
                    cwd=project_dir,
                    reference=_image_path(project_dir, asset_id) if media_type == "video" else None,
                    duration=provider_duration,
                    timeout=int(route.get("timeout", 3600)),
                    media_command_template=str(route.get("command", "")),
                    quality=str(route.get("quality", "")),
                    resolution=job.resolution,
                    aspect_ratio=job.aspect_ratio,
                )
            job.status = "review"
            job.error = None
            job.updated_at = utc_now()
            write_json(
                output.parent / "generation.json",
                {
                    **record,
                    "asset_id": asset_id,
                    "category": asset.category,
                    "linked_shots": asset.linked_shots,
                    "media_type": media_type,
                    "source_duration_seconds": asset.source_duration_seconds,
                    "provider_duration_seconds": (
                        float(route.get("duration_seconds") or asset.source_duration_seconds)
                        if media_type == "video"
                        else 0
                    ),
                    "provider": route.get("provider"),
                    "model": route.get("model"),
                    "quality": route.get("quality", ""),
                    "resolution": job.resolution,
                    "aspect_ratio": job.aspect_ratio,
                    "created_at": utc_now(),
                },
            )
        except Exception as exc:
            job.status = "manual_required" if str(route.get("provider")) == "manual_upload" else "failed"
            job.error = str(exc)
            job.updated_at = utc_now()
        write_json(_manifest_path(project_dir, media_type), manifest)
    return manifest


def approve_media(
    project_dir: Path,
    *,
    media_type: str,
    shot_ids: list[str] | None = None,
) -> V1MediaManifest:
    project_dir = Path(project_dir)
    plan = _generation_plan(project_dir)
    path = _manifest_path(project_dir, media_type)
    manifest = load_model(path, V1MediaManifest)
    wanted = _wanted_assets(plan, shot_ids)
    for job in manifest.jobs:
        asset_id = job.asset_id or job.shot_id
        if wanted and asset_id not in wanted:
            continue
        output = project_dir / str(job.output)
        if not output.exists():
            if media_type == "video" and _image_path(project_dir, asset_id).exists():
                job.status = "rejected"
                job.error = "retained approved package image instead of generated video"
                job.updated_at = utc_now()
                continue
            raise RuntimeError(f"cannot approve missing {media_type}: {asset_id}")
        job.status = "approved"
        job.error = None
        job.updated_at = utc_now()
    write_json(path, manifest)
    return manifest


def _run(command: list[str], *, timeout: int = 1200) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout)[-5000:])


def _voiceover_path(project_dir: Path) -> tuple[Path, AudioManifest]:
    manifest = load_model(project_dir / "04_voice/audio_manifest.json", AudioManifest)
    return project_dir / manifest.voiceover_wav, manifest


def _crop_filter(crop_id: str | None, width: int, height: int) -> str:
    if not crop_id:
        return f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    seed = sum(ord(char) for char in crop_id)
    horizontal = ["0", "(iw-ow)/2", "iw-ow"][seed % 3]
    vertical = ["0", "(ih-oh)/2", "ih-oh"][(seed // 3) % 3]
    return (
        f"scale={width * 6 // 5}:{height * 6 // 5}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}:{horizontal}:{vertical}"
    )


def _overlay_text(spec: OverlaySpec | None) -> str:
    if spec is None:
        return ""
    parts = [spec.type.replace("_", " ").upper()]
    if spec.elements:
        parts.append(" · ".join(item.replace("_", " ") for item in spec.elements[:4]))
    if spec.disclosure and spec.disclosure.required:
        parts.append(spec.disclosure.text)
    return "\n".join(parts)


def _coded_frame(
    destination: Path,
    shot: EditorialShot,
    width: int,
    height: int,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (width, height), "#050c14")
    draw = ImageDraw.Draw(image)
    try:
        title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", max(28, width // 34))
        body = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", max(18, width // 58))
    except Exception:
        title = body = ImageFont.load_default()
    margin = max(36, width // 18)
    draw.rectangle((margin, margin, width - margin, height - margin), outline="#5ed9c5", width=3)
    overlay_text = _overlay_text(shot.overlay) or shot.visual_mode.replace("_", " ").upper()
    draw.text((margin * 2, margin * 2), overlay_text, font=title, fill="#edf4f7")
    if shot.claim_ids:
        draw.text(
            (margin * 2, height - margin * 3),
            "Claims: " + ", ".join(shot.claim_ids[:6]),
            font=body,
            fill="#8ea5b1",
        )
    image.save(destination, "PNG")


def _image_clip(
    source: Path,
    target: Path,
    entry: TimelineEntry,
    *,
    width: int,
    height: int,
    fps: int,
) -> None:
    duration = entry.timeline_end - entry.timeline_start
    base = _crop_filter(entry.crop_id, width, height)
    if entry.playback_mode in {"callback", "crop"}:
        vf = f"{base},zoompan=z='min(zoom+0.00025,1.018)':d=1:s={width}x{height}:fps={fps}"
    else:
        vf = f"{base},fps={fps}"
    _run([
        "ffmpeg", "-y", "-loop", "1", "-i", str(source),
        "-t", f"{duration:.3f}", "-vf", vf, "-an", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", str(target),
    ])


def _video_clip(
    source: Path,
    target: Path,
    entry: TimelineEntry,
    *,
    width: int,
    height: int,
    fps: int,
) -> None:
    duration = entry.timeline_end - entry.timeline_start
    speed = max(0.05, entry.playback_speed)
    base = _crop_filter(entry.crop_id, width, height)
    vf = [base, f"setpts=PTS/{speed}", f"fps={fps}"]
    command = ["ffmpeg", "-y"]
    if entry.playback_mode in {"loop", "loop_and_slow", "callback", "overlay_background"}:
        command.extend(["-stream_loop", "-1"])
    command.extend(["-ss", f"{entry.source_in:.3f}", "-i", str(source)])
    source_length = None
    if entry.source_out is not None:
        source_length = max(0.1, entry.source_out - entry.source_in)
    if entry.playback_mode == "reverse_loop":
        vf.insert(1, "reverse")
        command[2:2] = ["-stream_loop", "-1"] if "-stream_loop" not in command else []
    if entry.playback_mode == "freeze":
        freeze_at = max(0.05, source_length or 0.2)
        vf.append(f"tpad=stop_mode=clone:stop_duration={max(0, duration - freeze_at):.3f}")
    command.extend(["-t", f"{duration:.3f}", "-vf", ",".join(vf), "-an"])
    command.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", str(target)])
    _run(command)


def _render_timeline_video(
    project_dir: Path,
    timeline: Timeline,
    *,
    root: Path,
    width: int,
    height: int,
    fps: int,
) -> tuple[Path, list[dict[str, Any]]]:
    work = root / "_render"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []
    decisions: list[dict[str, Any]] = []
    for index, entry in enumerate(timeline.entries, start=1):
        target = work / f"clip_{index:04d}.mp4"
        source = project_dir / entry.source_media if entry.source_media else None
        if entry.media_kind == "video" and source and source.exists():
            _video_clip(source, target, entry, width=width, height=height, fps=fps)
        elif entry.media_kind in {"image", "archive"} and source and source.exists():
            _image_clip(source, target, entry, width=width, height=height, fps=fps)
        else:
            still = work / f"coded_{index:04d}.png"
            editorial = _editorial_plan(project_dir)
            shot = next(item for item in editorial.shots if item.shot_id == entry.shot_id)
            _coded_frame(still, shot, width, height)
            _image_clip(still, target, entry, width=width, height=height, fps=fps)
            source = still
        clips.append(target)
        decisions.append({
            "shot_id": entry.shot_id,
            "master_asset": entry.master_asset,
            "kind": entry.media_kind,
            "source": str(source.relative_to(project_dir)) if source and project_dir in source.parents else str(source),
            "timeline_start": entry.timeline_start,
            "timeline_end": entry.timeline_end,
            "source_in": entry.source_in,
            "source_out": entry.source_out,
            "playback_mode": entry.playback_mode,
            "playback_speed": entry.playback_speed,
            "crop_id": entry.crop_id,
            "overlay_track_ids": entry.overlay_track_ids,
        })
    concat = work / "concat.txt"
    concat.write_text("\n".join(f"file '{path.as_posix()}'" for path in clips) + "\n", encoding="utf-8")
    video_only = work / "video_only.mp4"
    _run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
        "-c", "copy", str(video_only),
    ])
    return video_only, decisions


def render_animatic(
    project_dir: Path,
    *,
    width: int = 1280,
    height: int = 720,
    fps: int = 24,
) -> AnimaticManifest:
    project_dir = Path(project_dir)
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required to render the image-and-sound animatic")
    plan = _generation_plan(project_dir)
    images = load_model(project_dir / "07_images/jobs.json", V1MediaManifest)
    statuses = {(item.asset_id or item.shot_id): item for item in images.jobs}
    missing = [
        asset.asset_id for asset in plan.assets
        if statuses.get(asset.asset_id) is None or statuses[asset.asset_id].status != "approved"
    ]
    if missing:
        raise RuntimeError(
            "approve every master-package image before animatic rendering: "
            + ", ".join(missing)
        )
    timeline = build_timeline(project_dir)
    root = project_dir / "08_animatic"
    video_only, decisions = _render_timeline_video(
        project_dir,
        timeline,
        root=root,
        width=width,
        height=height,
        fps=fps,
    )
    voiceover, audio_manifest = _voiceover_path(project_dir)
    output = root / "animatic.mp4"
    _run([
        "ffmpeg", "-y", "-i", str(video_only), "-i", str(voiceover),
        "-f", "lavfi", "-t", f"{timeline.total_seconds:.3f}",
        "-i", "anoisesrc=color=pink:amplitude=0.004",
        "-filter_complex",
        "[1:a]volume=1.0[n];[2:a]lowpass=f=900,volume=0.18[a];"
        "[n][a]amix=inputs=2:duration=first:dropout_transition=0[m]",
        "-map", "0:v:0", "-map", "[m]", "-c:v", "copy", "-c:a", "aac",
        "-b:a", "192k", "-shortest", str(output),
    ])
    sound_plan = [
        {
            "shot_id": item.shot_id,
            "start": item.timeline_start,
            "end": item.timeline_end,
            "semantic_hint": "restrained ambience; narration remains dominant",
        }
        for item in timeline.entries
    ]
    write_json(
        root / "sound_plan.json",
        {
            "cues": sound_plan,
            "ambience": "subtle pink room tone under narration",
            "timeline_decisions": decisions,
        },
    )
    manifest = AnimaticManifest(
        project_id=timeline.project_id,
        output=str(output.relative_to(project_dir)),
        duration_seconds=timeline.total_seconds,
        voiceover_sha256=audio_manifest.voiceover_sha256,
        sound_plan="08_animatic/sound_plan.json",
        shots=[item.shot_id for item in timeline.entries],
    )
    write_json(root / "render_report.json", manifest)
    return manifest


def render_final_preview(
    project_dir: Path,
    *,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
) -> Path:
    project_dir = Path(project_dir)
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required to render the final preview")
    timeline = build_timeline(project_dir)
    root = project_dir / "10_final_preview"
    video_only, decisions = _render_timeline_video(
        project_dir,
        timeline,
        root=root,
        width=width,
        height=height,
        fps=fps,
    )
    voiceover, audio_manifest = _voiceover_path(project_dir)
    output = root / "final_preview.mp4"
    _run([
        "ffmpeg", "-y", "-i", str(video_only), "-i", str(voiceover),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
        "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(output),
    ])
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
            "-of", "json", str(output),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    ) if shutil.which("ffprobe") else None
    stream_types: set[str] = set()
    if probe and probe.returncode == 0:
        stream_types = {
            item.get("codec_type")
            for item in json.loads(probe.stdout).get("streams", [])
            if item.get("codec_type")
        }
        if not {"video", "audio"}.issubset(stream_types):
            raise RuntimeError("final preview must contain both video and audio streams")
    write_json(
        root / "render_report.json",
        {
            "project_id": timeline.project_id,
            "output": str(output.relative_to(project_dir)),
            "width": width,
            "height": height,
            "fps": fps,
            "voiceover_sha256": audio_manifest.voiceover_sha256,
            "stream_types": sorted(stream_types),
            "shots": decisions,
            "overlay_track_count": len(timeline.overlay_tracks),
            "created_at": utc_now(),
        },
    )
    return output


def transition_after_media(
    store: ProjectStore,
    project_id: str,
    media_type: str,
    manifest: V1MediaManifest,
) -> None:
    if any(item.status in {"review", "approved"} for item in manifest.jobs):
        store.transition(
            project_id,
            ProjectState.IMAGES_REVIEW if media_type == "image" else ProjectState.VIDEOS_REVIEW,
        )
    else:
        store.transition(
            project_id,
            ProjectState.IMAGES_GENERATING if media_type == "image" else ProjectState.VIDEOS_GENERATING,
        )
