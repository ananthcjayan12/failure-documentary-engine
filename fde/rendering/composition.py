from __future__ import annotations

import html
import json
import shutil
from pathlib import Path
from typing import Any

from ..io import load_model, write_json
from ..models import ProjectBrief, Timeline

VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}


def _link_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    try:
        destination.symlink_to(source.resolve())
    except OSError:
        shutil.copy2(source, destination)


def build(
    project_dir: Path, *, preview: bool, width: int, height: int, fps: int = 24,
    window: tuple[float, float] | None = None, composition_name: str | None = None,
) -> Path:
    timeline = load_model(project_dir / "12_timeline/timeline.json", Timeline)
    brief = load_model(project_dir / "00_input/project_brief.json", ProjectBrief)
    total_duration = float(timeline.total_seconds)
    window_start, window_end = window or (0.0, total_duration)
    if window_start < 0 or window_end <= window_start or window_end > total_duration + 1e-6:
        raise ValueError(f"Invalid composition window: {window_start:.6f}-{window_end:.6f}")
    base = project_dir / ("13_preview/composition" if preview else "14_final/composition")
    composition = base / composition_name if composition_name else base
    if composition.exists():
        shutil.rmtree(composition)
    assets_dir = composition / "assets"
    assets_dir.mkdir(parents=True)
    entries: list[dict[str, Any]] = []
    selected_entries = [
        entry for entry in timeline.entries
        if float(entry.end) > window_start and float(entry.start) < window_end
    ]
    for index, entry in enumerate(selected_entries, 1):
        if float(entry.start) < window_start - 1e-6 or float(entry.end) > window_end + 1e-6:
            raise ValueError(
                f"Composition window splits timeline entry {entry.timeline_id}: "
                f"{float(entry.start):.6f}-{float(entry.end):.6f}"
            )
        source = project_dir / entry.source_media if entry.source_media else None
        media_kind = entry.media_kind
        media_file = ""
        if source and source.exists():
            suffix = source.suffix.lower() or (".mp4" if media_kind == "video" else ".png")
            media_file = f"media-{index:04d}{suffix}"
            _link_or_copy(source, assets_dir / media_file)
        entries.append({
            **entry.model_dump(mode="json"),
            "media_file": media_file,
            "start": float(entry.start) - window_start,
            "end": float(entry.end) - window_start,
            "duration": float(entry.end - entry.start),
        })
    narration_candidates = list((project_dir / "11_narration").glob("narration_master.*"))
    if narration_candidates:
        _link_or_copy(narration_candidates[0], assets_dir / f"narration{narration_candidates[0].suffix.lower()}")
    manifest = {
        "project_id": brief.project_id,
        "title": brief.title,
        "width": width,
        "height": height,
        "fps": fps,
        "duration": float(window_end - window_start),
        "timeline_offset": window_start,
        "source_duration": total_duration,
        "entries": entries,
        "has_narration": bool(narration_candidates),
        "narration_file": f"narration{narration_candidates[0].suffix.lower()}" if narration_candidates else None,
        "preview": preview,
    }
    write_json(composition / "composition-manifest.json", manifest)
    (composition / "index.html").write_text(_html(manifest), encoding="utf-8")
    return composition / "index.html"


def _entry_markup(item: dict[str, Any], index: int) -> str:
    start = float(item["start"])
    duration = max(0.001, float(item["duration"]))
    media_file = html.escape(str(item.get("media_file") or ""))
    element_id = f"shot-{index:04d}"
    if not media_file:
        return (
            f'<section id="{element_id}" class="shot clip placeholder" data-start="{start:.6f}" '
            f'data-duration="{duration:.6f}" data-track-index="10"><div class="placeholder-copy">'
            f'{html.escape(str(item.get("master_asset") or "Visual pending"))}</div></section>'
        )
    if str(item.get("media_kind")) == "video" or Path(media_file).suffix.lower() in VIDEO_EXTENSIONS:
        return (
            f'<video id="{element_id}" class="shot media-video clip" data-start="{start:.6f}" '
            f'data-duration="{duration:.6f}" data-track-index="10" data-loop '
            f'src="assets/{media_file}" muted playsinline preload="auto"></video>'
        )
    return (
        f'<section id="{element_id}" class="shot clip" data-start="{start:.6f}" '
        f'data-duration="{duration:.6f}" data-track-index="10">'
        f'<img class="media-image" src="assets/{media_file}" alt="" /></section>'
    )


def _html(manifest: dict[str, Any]) -> str:
    entries_markup = "\n".join(_entry_markup(item, index) for index, item in enumerate(manifest["entries"], 1))
    entries_json = json.dumps([
        {"id": f"shot-{index:04d}", "start": item["start"], "end": item["end"], "kind": item["media_kind"]}
        for index, item in enumerate(manifest["entries"], 1)
    ], ensure_ascii=False)
    template = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Failure Investigation Composition</title>
<style>
:root{--ink:#eef4f8;--muted:#9babbb;--teal:#6ee7c8;--navy:#07111c}
*{box-sizing:border-box}
html,body{margin:0;background:#02060b;color:var(--ink);font-family:Inter,ui-sans-serif,system-ui,-apple-system,sans-serif;overflow:hidden}
#stage{position:relative;width:__WIDTH__px;height:__HEIGHT__px;overflow:hidden;background:#07111c;transform-origin:top left}
.shot{position:absolute;inset:0;width:100%;height:100%;opacity:0;overflow:hidden;background:#07111c}
.media-image,.media-video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;will-change:transform,opacity}
.placeholder{display:grid;place-items:center;background:radial-gradient(circle at 50% 35%,#18304a,#07111c 65%)}
.placeholder-copy{max-width:70%;padding:30px;border:1px solid rgba(110,231,200,.3);border-radius:18px;color:var(--teal);font-weight:750;font-size:38px;text-align:center}
#grade{position:absolute;inset:0;z-index:60;pointer-events:none;background:linear-gradient(180deg,rgba(0,0,0,.12),transparent 25%,transparent 70%,rgba(0,0,0,.30));mix-blend-mode:multiply}
#grain{position:absolute;inset:-20%;z-index:61;pointer-events:none;opacity:.055;background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.8'/%3E%3C/svg%3E")}
#project-label{position:absolute;z-index:70;left:3.2%;top:4%;padding:8px 13px;border:1px solid rgba(255,255,255,.22);border-radius:999px;background:rgba(3,10,18,.42);font-size:15px;font-weight:750;letter-spacing:.08em;text-transform:uppercase;opacity:.72}
</style>
</head>
<body>
<div id="stage" data-composition-id="failure-documentary" data-no-timeline data-start="0" data-duration="__DURATION__" data-width="__WIDTH__" data-height="__HEIGHT__" data-fps="__FPS__">
__ENTRIES__
<div id="grade"></div><div id="grain"></div><div id="project-label">__TITLE__</div>
</div>
<script>
const ENTRIES=__ENTRIES_JSON__;
const clamp=(v,a=0,b=1)=>Math.max(a,Math.min(b,v));
const ease=v=>1-Math.pow(1-clamp(v),3);
function renderAt(t){
  for(const item of ENTRIES){
    const el=document.getElementById(item.id);if(!el)continue;
    const active=t>=item.start&&t<item.end;
    if(!active){el.style.opacity='0';continue}
    const d=Math.max(.001,item.end-item.start),p=(t-item.start)/d;
    const intro=ease(clamp(p/.08)),outro=ease(clamp((1-p)/.08));
    el.style.opacity=String(Math.min(intro,outro));
    const media=el.tagName==='VIDEO'?el:el.querySelector('img,video');
    if(media){const drift=(p-.5)*1.2;media.style.transform=`scale(${1.025+.025*p}) translate3d(${drift}%,0,0)`}
  }
}
window.addEventListener('hf-seek',e=>renderAt(Number(e.detail.time||0)));
renderAt(0);window.__hf_ready__=true;
</script>
</body></html>'''
    replacements = {
        "__WIDTH__": str(manifest["width"]), "__HEIGHT__": str(manifest["height"]),
        "__DURATION__": f"{manifest['duration']:.6f}", "__FPS__": str(manifest["fps"]),
        "__ENTRIES__": entries_markup, "__ENTRIES_JSON__": entries_json,
        "__TITLE__": html.escape(str(manifest["title"])),
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template
