from __future__ import annotations

import os
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .io import load_model
from .media import has_command, run_command
from .models import ProjectBrief, Timeline


def _placeholder(path: Path, text: str, width: int, height: int) -> None:
    image = Image.new("RGB", (width, height), "#07131c")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
    except Exception:
        font = ImageFont.load_default()
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(((width - (box[2]-box[0]))/2, (height-(box[3]-box[1]))/2), text, font=font, fill="#d49349")
    image.save(path)


def render_ffmpeg(project_dir: Path, *, preview: bool, width: int, height: int) -> Path:
    if not has_command("ffmpeg"):
        raise RuntimeError("FFmpeg is required for rendering")
    timeline = load_model(project_dir / "12_timeline/timeline.json", Timeline)
    brief = load_model(project_dir / "00_input/project_brief.json", ProjectBrief)
    work = project_dir / ("13_preview/_render" if preview else "14_final/_render")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    clips: list[Path] = []
    placeholder = work / "placeholder.png"
    _placeholder(placeholder, brief.title, width, height)
    for index, entry in enumerate(timeline.entries, 1):
        duration = max(0.1, entry.end - entry.start)
        source = project_dir / entry.source_media if entry.source_media else placeholder
        target = work / f"clip_{index:04d}.mp4"
        vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps=24"
        if entry.media_kind == "video" and source.exists():
            command = [
                "ffmpeg", "-y", "-stream_loop", "-1", "-i", str(source),
                "-t", f"{duration:.3f}", "-vf", vf, "-an", "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(target),
            ]
        else:
            image_source = source if source.exists() else placeholder
            command = [
                "ffmpeg", "-y", "-loop", "1", "-i", str(image_source),
                "-t", f"{duration:.3f}", "-vf", vf, "-an", "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(target),
            ]
        run_command(command)
        clips.append(target)
    concat_file = work / "concat.txt"
    concat_file.write_text("\n".join(f"file '{clip.as_posix()}'" for clip in clips) + "\n", encoding="utf-8")
    video_only = work / "video_only.mp4"
    run_command(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(video_only)])
    narration_candidates = list((project_dir / "11_narration").glob("narration_master.*"))
    out = project_dir / ("13_preview/preview_v01.mp4" if preview else "14_final/picture_locked_base.mp4")
    if narration_candidates:
        run_command([
            "ffmpeg", "-y", "-i", str(video_only), "-i", str(narration_candidates[0]),
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
            "-b:a", "192k", "-shortest", str(out),
        ])
    else:
        shutil.copy2(video_only, out)
    return out


def render(project_dir: Path, *, preview: bool, width: int, height: int) -> Path:
    """Dispatch to the selected deterministic renderer with an explicit fallback."""
    provider = os.environ.get("FDE_RENDER_PROVIDER", "ffmpeg").strip() or "ffmpeg"
    fallback = os.environ.get("FDE_RENDER_FALLBACK_PROVIDER", "ffmpeg").strip() or "ffmpeg"
    if provider == "mock":
        provider = "ffmpeg"
    if provider == "hyperframes":
        out = project_dir / ("13_preview/preview_v01.mp4" if preview else "14_final/picture_locked_base.mp4")
        try:
            from .rendering.hyperframes import render as render_hyperframes
            render_hyperframes(project_dir, preview=preview, width=width, height=height, output=out)
            return out
        except Exception:
            if fallback != "ffmpeg":
                raise
            return render_ffmpeg(project_dir, preview=preview, width=width, height=height)
    if provider == "ffmpeg":
        return render_ffmpeg(project_dir, preview=preview, width=width, height=height)
    raise RuntimeError(f"Unsupported render provider: {provider}")
