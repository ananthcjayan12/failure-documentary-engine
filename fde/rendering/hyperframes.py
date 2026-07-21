from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..io import load_model, write_json
from ..models import Timeline
from .composition import build

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def binary() -> list[str]:
    explicit = os.getenv("FDE_HYPERFRAMES_BIN", "").strip()
    if explicit:
        return [explicit]
    global_binary = shutil.which("hyperframes")
    if global_binary:
        return [global_binary]
    local = PROJECT_ROOT / "node_modules/.bin/hyperframes"
    if local.exists():
        return [str(local)]
    npx = shutil.which("npx")
    if npx:
        return [npx, "hyperframes"]
    raise RuntimeError("HyperFrames is not installed. Run `npm install` and `npm run doctor`.")


def validate(project_dir: Path, *, preview: bool, width: int, height: int) -> dict[str, Any]:
    composition = build(project_dir, preview=preview, width=width, height=height)
    command = [*binary(), "lint", ".", "--json"]
    result = subprocess.run(command, cwd=composition.parent, capture_output=True, text=True, timeout=600)
    report = {"returncode": result.returncode, "stdout": result.stdout[-12000:], "stderr": result.stderr[-12000:]}
    if result.returncode != 0:
        raise RuntimeError(f"HyperFrames lint failed: {(result.stderr or result.stdout)[-4000:]}")
    return report


def chunk_windows(timeline: Timeline, max_seconds: float = 30.0) -> list[tuple[float, float]]:
    """Create entry-aligned render windows so a restart never repeats the full film."""
    if max_seconds <= 0:
        raise ValueError("max_seconds must be positive")
    entries = sorted(timeline.entries, key=lambda item: (float(item.start), float(item.end)))
    total = float(timeline.total_seconds)
    if not entries:
        return [(0.0, total)]
    windows: list[tuple[float, float]] = []
    start = 0.0
    previous_end = 0.0
    for entry in entries:
        end = float(entry.end)
        if previous_end > start and end - start > max_seconds:
            windows.append((start, previous_end))
            start = previous_end
        previous_end = max(previous_end, end)
    if previous_end < total:
        previous_end = total
    if previous_end > start:
        windows.append((start, previous_end))
    return windows or [(0.0, total)]


def _run_hyperframes(composition: Path, output: Path, log: Path) -> None:
    command = [*binary(), "render", "-c", composition.name, "-o", str(output.resolve())]
    result = subprocess.run(command, cwd=composition.parent, capture_output=True, text=True, timeout=14400)
    log.write_text((result.stdout or "") + "\n" + (result.stderr or ""), encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"HyperFrames render failed: {(result.stderr or result.stdout)[-5000:]}")
    if not output.exists():
        raise RuntimeError("HyperFrames completed without producing an MP4")


def _valid_existing(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 1024:
        return False
    if not shutil.which("ffprobe"):
        return True
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def _concat(chunks: list[Path], output: Path) -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg is required to concatenate resumable HyperFrames chunks")
    manifest = output.parent / f"{output.stem}.chunks.ffconcat"
    manifest.write_text(
        "ffconcat version 1.0\n" + "\n".join(f"file '{item.resolve().as_posix()}'" for item in chunks) + "\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(manifest), "-c", "copy", str(output)],
        capture_output=True, text=True, timeout=3600,
    )
    (output.parent / "hyperframes-concat.log").write_text(
        (result.stdout or "") + "\n" + (result.stderr or ""), encoding="utf-8"
    )
    if result.returncode != 0:
        raise RuntimeError(f"HyperFrames chunk concat failed: {(result.stderr or result.stdout)[-5000:]}")


def render(project_dir: Path, *, preview: bool, width: int, height: int, output: Path) -> dict[str, Any]:
    timeline = load_model(project_dir / "12_timeline/timeline.json", Timeline)
    output.parent.mkdir(parents=True, exist_ok=True)
    lint = validate(project_dir, preview=preview, width=width, height=height)
    (output.parent / "hyperframes-lint.log").write_text(
        (lint.get("stdout") or "") + "\n" + (lint.get("stderr") or ""), encoding="utf-8"
    )
    max_seconds = float(os.getenv("FDE_HYPERFRAMES_CHUNK_SECONDS", "30"))
    windows = chunk_windows(timeline, max_seconds=max_seconds)
    chunk_root = output.parent / f"{output.stem}.hyperframes-chunks"
    chunk_root.mkdir(parents=True, exist_ok=True)
    chunks: list[Path] = []
    rendered: list[dict[str, Any]] = []
    for index, window in enumerate(windows, 1):
        chunk = chunk_root / f"part-{index:03d}.mp4"
        chunks.append(chunk)
        if _valid_existing(chunk):
            rendered.append({"index": index, "window": window, "path": str(chunk), "status": "resumed"})
            continue
        composition = build(
            project_dir, preview=preview, width=width, height=height,
            window=window, composition_name=f"chunks/part-{index:03d}",
        )
        _run_hyperframes(composition, chunk, chunk.with_suffix(".render.log"))
        rendered.append({"index": index, "window": window, "path": str(chunk), "status": "rendered"})
    video_only = output.parent / (output.stem + ".hyperframes-video.mp4")
    _concat(chunks, video_only)
    narration = next(iter((project_dir / "11_narration").glob("narration_master.*")), None)
    if narration and shutil.which("ffmpeg"):
        mux = subprocess.run([
            "ffmpeg", "-y", "-i", str(video_only), "-i", str(narration),
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
            "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(output),
        ], capture_output=True, text=True, timeout=1800)
        (output.parent / "hyperframes-mux.log").write_text(
            (mux.stdout or "") + "\n" + (mux.stderr or ""), encoding="utf-8"
        )
        if mux.returncode != 0:
            raise RuntimeError(f"Narration mux failed: {(mux.stderr or mux.stdout)[-4000:]}")
    else:
        shutil.copy2(video_only, output)
    report = {
        "composition": str(project_dir / ("13_preview/composition" if preview else "14_final/composition")),
        "output": str(output), "renderer": "hyperframes", "chunk_seconds": max_seconds,
        "windows": rendered,
    }
    write_json(output.parent / "hyperframes-render-report.json", report)
    return report
