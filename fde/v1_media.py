from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .io import load_model, write_json
from .models import (
    AnimaticManifest,
    AudioManifest,
    ProjectState,
    ShotPlan,
    V1MediaJob,
    V1MediaManifest,
    utc_now,
)
from .models import MasterAssetPlan
from .project import ProjectStore
from .providers.media_factory import generate_one


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


def _load_shots(project_dir: Path) -> ShotPlan:
    return load_model(project_dir / "06_shots/shot_plan.json", ShotPlan)


def _image_path(project_dir: Path, shot_id: str) -> Path:
    return project_dir / "07_images" / shot_id / "image.png"


def _video_path(project_dir: Path, shot_id: str) -> Path:
    return project_dir / "09_videos" / shot_id / "approved.mp4"


def _asset_sources(project_dir: Path, shots: ShotPlan) -> tuple[list[str], dict[str, str], dict[str, str]]:
    """Return reusable media IDs and their shot/prompt mappings.

    Older projects without an asset plan remain readable, but all newly approved
    shot plans receive a bounded master-asset plan before image work begins.
    """
    path = project_dir / "05_master_assets/master_assets.json"
    if not path.exists():
        ids = [shot.shot_id for shot in shots.shots]
        return ids, {shot.shot_id: shot.shot_id for shot in shots.shots}, {shot.shot_id: shot.shot_id for shot in shots.shots}
    plan = load_model(path, MasterAssetPlan)
    source_for_shot = {shot_id: asset.asset_id for asset in plan.assets for shot_id in asset.linked_shots}
    missing = [shot.shot_id for shot in shots.shots if shot.shot_id not in source_for_shot]
    if missing:
        raise RuntimeError(f"master asset plan leaves shots uncovered: {', '.join(missing)}")
    first_shot = {asset.asset_id: asset.linked_shots[0] for asset in plan.assets}
    return [asset.asset_id for asset in plan.assets], source_for_shot, first_shot


def _mock_image(destination: Path, shot_id: str, narration: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1600, 900), "#07131f")
    draw = ImageDraw.Draw(image)
    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 62)
        body_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
    except Exception:
        title_font = body_font = ImageFont.load_default()
    draw.rounded_rectangle((80, 80, 1520, 820), radius=28, outline="#5ed9c5", width=4)
    draw.text((130, 130), shot_id, font=title_font, fill="#5ed9c5")
    wrapped = narration[:180]
    lines = [wrapped[index:index + 65] for index in range(0, len(wrapped), 65)]
    for index, line in enumerate(lines[:3]):
        draw.text((130, 270 + index * 55), line, font=body_font, fill="#edf4f7")
    draw.text((130, 700), "V1 IMAGE REVIEW PLACEHOLDER", font=body_font, fill="#8ea5b1")
    image.save(destination, "PNG")


def prepare_media_jobs(
    project_dir: Path,
    media_type: str,
    route: dict[str, Any] | None = None,
) -> V1MediaManifest:
    if media_type not in {"image", "video"}:
        raise ValueError("media_type must be image or video")
    project_dir = Path(project_dir)
    route = route or _route_from_env(media_type)
    shots = _load_shots(project_dir)
    source_ids, _, first_shot = _asset_sources(project_dir, shots)
    asset_plan_path = project_dir / "05_master_assets/master_assets.json"
    assets = {item.asset_id: item for item in load_model(asset_plan_path, MasterAssetPlan).assets} if asset_plan_path.exists() else {}
    existing_path = _manifest_path(project_dir, media_type)
    existing = load_model(existing_path, V1MediaManifest) if existing_path.exists() else None
    existing_by_id = {item.shot_id: item for item in existing.jobs} if existing else {}
    resolution = str(route.get("resolution") or ("2K" if media_type == "image" else "720p"))
    aspect_ratio = str(route.get("aspect_ratio") or "16:9")
    jobs: list[V1MediaJob] = []
    shot_by_id = {shot.shot_id: shot for shot in shots.shots}
    for source_id in source_ids:
        shot = shot_by_id[first_shot[source_id]]
        old = existing_by_id.get(source_id)
        asset = assets.get(source_id)
        prompt = (asset.image_prompt if media_type == "image" else asset.video_prompt) if asset else (shot.image_prompt if media_type == "image" else shot.video_prompt)
        output = str((_image_path(project_dir, source_id) if media_type == "image" else _video_path(project_dir, source_id)).relative_to(project_dir))
        reference = str(_image_path(project_dir, source_id).relative_to(project_dir)) if media_type == "video" else None
        duration = 0 if media_type == "image" else 5
        if (
            old and old.prompt == prompt and old.duration_seconds == duration
            and old.resolution == resolution and old.aspect_ratio == aspect_ratio
        ):
            jobs.append(old)
            continue
        jobs.append(V1MediaJob(
            job_id=f"{media_type.upper()}_{source_id}", shot_id=source_id,
            media_type=media_type, status="pending", prompt=prompt, output=output,
            reference=reference, duration_seconds=duration,
            resolution=resolution, aspect_ratio=aspect_ratio,
        ))
        job_dir = project_dir / ("07_images" if media_type == "image" else "09_videos") / source_id
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "prompt.txt").write_text(prompt.rstrip() + "\n", encoding="utf-8")
    manifest = V1MediaManifest(project_id=shots.project_id, media_type=media_type, jobs=jobs)
    write_json(existing_path, manifest)
    write_json(existing_path.parent / "route_snapshot.json", {
        "provider": route.get("provider"), "model": route.get("model"),
        "quality": route.get("quality"), "resolution": resolution,
        "aspect_ratio": aspect_ratio, "provider_duration_seconds": route.get("duration_seconds", 0),
        "updated_at": utc_now(),
    })
    return manifest


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
    manifest = prepare_media_jobs(project_dir, media_type, route=route)
    wanted = set(shot_ids or [])
    shot_plan = _load_shots(project_dir)
    _, source_for_shot, first_shot = _asset_sources(project_dir, shot_plan)
    shots = {item.shot_id: item for item in shot_plan.shots}
    for job in manifest.jobs:
        if wanted and job.shot_id not in wanted and not any(source_for_shot.get(shot_id) == job.shot_id for shot_id in wanted):
            continue
        output = project_dir / str(job.output)
        if output.exists() and job.status in {"review", "approved"} and not force:
            continue
        if media_type == "video" and not _image_path(project_dir, job.shot_id).exists():
            job.status = "failed"
            job.error = "approved source image is required before video generation"
            job.updated_at = utc_now()
            write_json(_manifest_path(project_dir, media_type), manifest)
            continue
        job.status = "generating"
        job.error = None
        job.updated_at = utc_now()
        write_json(_manifest_path(project_dir, media_type), manifest)
        try:
            provider = str(route.get("provider", "mock"))
            if provider == "mock" and media_type == "image":
                _mock_image(output, job.shot_id, shots[first_shot[job.shot_id]].narration_text)
                record = {"provider": "mock", "model": route.get("model"), "path": str(output)}
            else:
                provider_duration = float(route.get("duration_seconds") or job.duration_seconds)
                record = generate_one(
                    provider=provider, model=str(route.get("model", "")), prompt=job.prompt,
                    destination=output, media_type=media_type, cwd=project_dir,
                    reference=_image_path(project_dir, job.shot_id) if media_type == "video" else None,
                    duration=provider_duration, timeout=int(route.get("timeout", 3600)),
                    media_command_template=str(route.get("command", "")),
                    quality=str(route.get("quality", "")), resolution=job.resolution,
                    aspect_ratio=job.aspect_ratio,
                )
            job.status = "review"
            job.error = None
            job.updated_at = utc_now()
            write_json(output.parent / "generation.json", {
                **record, "shot_id": job.shot_id, "media_type": media_type,
                "timeline_duration_seconds": job.duration_seconds,
                "provider_duration_seconds": float(route.get("duration_seconds") or job.duration_seconds),
                "provider": route.get("provider"), "model": route.get("model"),
                "quality": route.get("quality", ""), "resolution": job.resolution,
                "aspect_ratio": job.aspect_ratio, "created_at": utc_now(),
            })
        except Exception as exc:
            job.status = "manual_required" if str(route.get("provider")) == "manual_upload" else "failed"
            job.error = str(exc)
            job.updated_at = utc_now()
        write_json(_manifest_path(project_dir, media_type), manifest)
    return manifest


def approve_media(project_dir: Path, *, media_type: str, shot_ids: list[str] | None = None) -> V1MediaManifest:
    project_dir = Path(project_dir)
    path = _manifest_path(project_dir, media_type)
    manifest = load_model(path, V1MediaManifest)
    wanted = set(shot_ids or [])
    for job in manifest.jobs:
        if wanted and job.shot_id not in wanted:
            continue
        output = project_dir / str(job.output)
        if not output.exists():
            if media_type == "video" and _image_path(project_dir, job.shot_id).exists():
                job.status = "rejected"
                job.error = "retained approved image instead of generated video"
                job.updated_at = utc_now()
                continue
            raise RuntimeError(f"cannot approve missing {media_type}: {job.shot_id}")
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


def render_animatic(project_dir: Path, *, width: int = 1280, height: int = 720, fps: int = 24) -> AnimaticManifest:
    project_dir = Path(project_dir)
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required to render the image-and-sound animatic")
    shots = _load_shots(project_dir)
    _, source_for_shot, _ = _asset_sources(project_dir, shots)
    images = load_model(project_dir / "07_images/jobs.json", V1MediaManifest)
    status = {item.shot_id: item for item in images.jobs}
    missing = [shot.shot_id for shot in shots.shots if status.get(source_for_shot[shot.shot_id]) is None or status[source_for_shot[shot.shot_id]].status != "approved"]
    if missing:
        raise RuntimeError(f"approve every shot image before animatic rendering: {', '.join(missing)}")
    root = project_dir / "08_animatic"
    work = root / "_render"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []
    sound_plan: list[dict[str, Any]] = []
    for index, shot in enumerate(shots.shots, start=1):
        source = _image_path(project_dir, source_for_shot[shot.shot_id])
        target = work / f"clip_{index:04d}.mp4"
        zoom = "zoompan=z='min(zoom+0.00035,1.025)':d=1"
        vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},{zoom}:s={width}x{height}:fps={fps}"
        _run([
            "ffmpeg", "-y", "-loop", "1", "-i", str(source), "-t", f"{shot.duration:.3f}",
            "-vf", vf, "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target),
        ])
        clips.append(target)
        cue = project_dir / "08_animatic/sfx" / f"{shot.shot_id}.wav"
        sound_plan.append({
            "shot_id": shot.shot_id, "start": shot.start, "end": shot.end,
            "hint": shot.sound_hint, "file": str(cue.relative_to(project_dir)) if cue.exists() else None,
        })
    concat = work / "concat.txt"
    concat.write_text("\n".join(f"file '{path.as_posix()}'" for path in clips) + "\n", encoding="utf-8")
    video_only = work / "video_only.mp4"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(video_only)])
    voiceover, audio_manifest = _voiceover_path(project_dir)
    output = root / "animatic.mp4"
    _run([
        "ffmpeg", "-y", "-i", str(video_only), "-i", str(voiceover),
        "-f", "lavfi", "-t", f"{shots.total_seconds:.3f}", "-i", "anoisesrc=color=pink:amplitude=0.004",
        "-filter_complex", "[1:a]volume=1.0[n];[2:a]lowpass=f=900,volume=0.18[a];[n][a]amix=inputs=2:duration=first:dropout_transition=0[m]",
        "-map", "0:v:0", "-map", "[m]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(output),
    ])
    write_json(root / "sound_plan.json", {"cues": sound_plan, "ambience": "subtle pink room tone under narration"})
    manifest = AnimaticManifest(
        project_id=shots.project_id, output=str(output.relative_to(project_dir)),
        duration_seconds=shots.total_seconds, voiceover_sha256=audio_manifest.voiceover_sha256,
        sound_plan="08_animatic/sound_plan.json", shots=[item.shot_id for item in shots.shots],
    )
    write_json(root / "render_report.json", manifest)
    return manifest


def render_final_preview(project_dir: Path, *, width: int = 1920, height: int = 1080, fps: int = 30) -> Path:
    project_dir = Path(project_dir)
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required to render the final preview")
    shots = _load_shots(project_dir)
    _, source_for_shot, _ = _asset_sources(project_dir, shots)
    image_jobs = load_model(project_dir / "07_images/jobs.json", V1MediaManifest)
    images = {item.shot_id: item for item in image_jobs.jobs}
    video_path = project_dir / "09_videos/jobs.json"
    videos = {item.shot_id: item for item in load_model(video_path, V1MediaManifest).jobs} if video_path.exists() else {}
    root = project_dir / "10_final_preview"
    work = root / "_render"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []
    decisions: list[dict[str, Any]] = []
    for index, shot in enumerate(shots.shots, start=1):
        source_id = source_for_shot[shot.shot_id]
        video_job = videos.get(source_id)
        source_video = _video_path(project_dir, source_id)
        target = work / f"clip_{index:04d}.mp4"
        vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps={fps}"
        if video_job and video_job.status == "approved" and source_video.exists():
            _run([
                "ffmpeg", "-y", "-stream_loop", "-1", "-i", str(source_video), "-t", f"{shot.duration:.3f}",
                "-vf", vf, "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target),
            ])
            kind, source = "video", source_video
        else:
            image_job = images.get(source_id)
            source_image = _image_path(project_dir, source_id)
            if not image_job or image_job.status != "approved" or not source_image.exists():
                raise RuntimeError(f"shot {shot.shot_id} has neither approved video nor approved image")
            _run([
                "ffmpeg", "-y", "-loop", "1", "-i", str(source_image), "-t", f"{shot.duration:.3f}",
                "-vf", vf, "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target),
            ])
            kind, source = "image", source_image
        clips.append(target)
        decisions.append({"shot_id": shot.shot_id, "kind": kind, "source": str(source.relative_to(project_dir))})
    concat = work / "concat.txt"
    concat.write_text("\n".join(f"file '{path.as_posix()}'" for path in clips) + "\n", encoding="utf-8")
    video_only = work / "video_only.mp4"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(video_only)])
    voiceover, audio_manifest = _voiceover_path(project_dir)
    output = root / "final_preview.mp4"
    _run([
        "ffmpeg", "-y", "-i", str(video_only), "-i", str(voiceover),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart", str(output),
    ])
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(output)],
        capture_output=True, text=True, timeout=60,
    ) if shutil.which("ffprobe") else None
    stream_types = set()
    if probe and probe.returncode == 0:
        stream_types = {item.get("codec_type") for item in json.loads(probe.stdout).get("streams", [])}
        if not {"video", "audio"}.issubset(stream_types):
            raise RuntimeError("final preview must contain both video and audio streams")
    write_json(root / "render_report.json", {
        "project_id": shots.project_id, "output": str(output.relative_to(project_dir)),
        "width": width, "height": height, "fps": fps,
        "voiceover_sha256": audio_manifest.voiceover_sha256,
        "stream_types": sorted(stream_types), "shots": decisions, "created_at": utc_now(),
    })
    return output


def transition_after_media(store: ProjectStore, project_id: str, media_type: str, manifest: V1MediaManifest) -> None:
    if any(item.status in {"review", "approved"} for item in manifest.jobs):
        store.transition(project_id, ProjectState.IMAGES_REVIEW if media_type == "image" else ProjectState.VIDEOS_REVIEW)
    else:
        store.transition(project_id, ProjectState.IMAGES_GENERATING if media_type == "image" else ProjectState.VIDEOS_GENERATING)
