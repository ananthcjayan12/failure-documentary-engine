from __future__ import annotations

import html
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .io import load_model
from .models import DocumentaryScript, MasterAssetPlan, ShotSkeletonPlan


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int, max_lines: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and len(" ".join(lines).split()) < len(words):
        lines[-1] = lines[-1].rstrip(".,") + "…"
    return lines


def generate_contact_sheet(project_dir: Path, width: int = 4096, height: int = 6144) -> dict[str, str]:
    brief_path = project_dir / "00_input/project_brief.json"
    from .models import ProjectBrief
    brief = load_model(brief_path, ProjectBrief)
    plan = load_model(project_dir / "05_master_assets/master_assets.json", MasterAssetPlan)
    skeleton = load_model(project_dir / "06_shots/shot_skeleton.json", ShotSkeletonPlan)
    script = load_model(project_dir / "03_narration/narration.json", DocumentaryScript)
    shots = {s.shot_id: s for s in skeleton.shots}
    narration = {n.narration_id: n for n in script.segments}

    canvas = Image.new("RGB", (width, height), "#07131c")
    draw = ImageDraw.Draw(canvas)
    title_size = 116
    title_text = f"{brief.title.upper()} — MASTER FOOTAGE CONTACT SHEET"
    title_font = _font(title_size, True)
    while title_size > 54 and draw.textlength(title_text, font=title_font) > width - 360:
        title_size -= 4
        title_font = _font(title_size, True)
    subtitle_font = _font(44)
    header_font = _font(38, True)
    body_font = _font(30)
    small_font = _font(24)
    status_font = _font(26, True)

    draw.rectangle((0, 0, width, 300), fill="#0b202d")
    draw.text((180, 70), title_text, font=title_font, fill="#eef6f8")
    draw.text((184, 210), f"{len(plan.assets)} reusable assets · {len(skeleton.shots)} shot divisions · target {brief.target_duration_seconds:.0f}s", font=subtitle_font, fill="#d49349")

    cols, rows = 4, 7
    gap = 26
    margin_x = 120
    top = 360
    tile_w = (width - 2 * margin_x - (cols - 1) * gap) // cols
    tile_h = (height - top - 140 - (rows - 1) * gap) // rows

    for index in range(cols * rows):
        row, col = divmod(index, cols)
        x = margin_x + col * (tile_w + gap)
        y = top + row * (tile_h + gap)
        draw.rounded_rectangle((x, y, x + tile_w, y + tile_h), radius=18, fill="#0d2532", outline="#315363", width=3)
        if index >= len(plan.assets):
            draw.text((x + 35, y + 35), "RESERVED", font=header_font, fill="#45616d")
            continue
        asset = plan.assets[index]
        image_box = (x + 22, y + 80, x + tile_w - 22, y + 330)
        image_path = project_dir / asset.approved_image if asset.approved_image else None
        if image_path and image_path.exists():
            with Image.open(image_path) as source:
                source = source.convert("RGB")
                target_w = image_box[2] - image_box[0]
                target_h = image_box[3] - image_box[1]
                source_ratio = source.width / source.height
                target_ratio = target_w / target_h
                if source_ratio > target_ratio:
                    new_h = target_h
                    new_w = int(new_h * source_ratio)
                else:
                    new_w = target_w
                    new_h = int(new_w / source_ratio)
                source = source.resize((new_w, new_h))
                left = max(0, (new_w - target_w) // 2)
                upper = max(0, (new_h - target_h) // 2)
                source = source.crop((left, upper, left + target_w, upper + target_h))
                canvas.paste(source, (image_box[0], image_box[1]))
        else:
            draw.rectangle(image_box, fill="#122f3d")
            draw.text((image_box[0] + 30, image_box[1] + 95), "IMAGE PENDING", font=header_font, fill="#6f8c98")

        draw.text((x + 24, y + 20), asset.asset_id, font=header_font, fill="#d49349")
        status = asset.image_review.status.value.upper()
        status_fill = "#77d1b3" if status == "APPROVED" else "#e1b267" if status == "PENDING" else "#e78378"
        status_width = draw.textlength(status, font=status_font)
        draw.text((x + tile_w - status_width - 24, y + 28), status, font=status_font, fill=status_fill)

        text_y = y + 352
        for line in _wrap(draw, asset.title, header_font, tile_w - 48, 2):
            draw.text((x + 24, text_y), line, font=header_font, fill="#f2f6f7")
            text_y += 46

        linked_shots = [shots[sid] for sid in asset.linked_shots if sid in shots]
        narration_ids = []
        for shot in linked_shots:
            narration_ids.extend(shot.narration_ids)
        narration_ids = list(dict.fromkeys(narration_ids))
        narration_text = " ".join(narration[n].text for n in narration_ids if n in narration)
        start = min((s.start for s in linked_shots), default=0)
        end = max((s.start + s.duration for s in linked_shots), default=0)
        metadata = f"Shots: {', '.join(asset.linked_shots[:5])}{'…' if len(asset.linked_shots) > 5 else ''}  |  {start:.0f}–{end:.0f}s  |  Uses: {asset.required_reuse_count}"
        draw.text((x + 24, text_y + 6), metadata, font=small_font, fill="#79b5c4")
        text_y += 46
        for line in _wrap(draw, narration_text or asset.primary_use, body_font, tile_w - 48, 4):
            draw.text((x + 24, text_y), line, font=body_font, fill="#c7d6da")
            text_y += 36
        text_y += 8
        motion = "; ".join(sorted({s.story_function for s in linked_shots if s.story_function})) or "Subtle controlled movement"
        for line in _wrap(draw, "ANIMATION: " + motion, small_font, tile_w - 48, 3):
            draw.text((x + 24, text_y), line, font=small_font, fill="#d49349")
            text_y += 30

    draw.text((120, height - 90), "Production-review document · full narration and prompts are available in contact_sheet.html", font=small_font, fill="#78909a")
    out_dir = project_dir / "06_contact_sheet"
    out_dir.mkdir(parents=True, exist_ok=True)
    png_path = out_dir / "contact_sheet.png"
    pdf_path = out_dir / "contact_sheet.pdf"
    canvas.save(png_path, "PNG", optimize=True)
    canvas.save(pdf_path, "PDF", resolution=150)

    cards = []
    for asset in plan.assets:
        linked_shots = [shots[sid] for sid in asset.linked_shots if sid in shots]
        narration_ids = list(dict.fromkeys(nid for s in linked_shots for nid in s.narration_ids))
        full_narration = " ".join(narration[n].text for n in narration_ids if n in narration)
        image_rel = asset.approved_image or ""
        cards.append(f"""
        <article>
          <h2>{html.escape(asset.asset_id)} — {html.escape(asset.title)}</h2>
          <p><strong>Status:</strong> {html.escape(asset.image_review.status.value)}</p>
          {f'<img src="../{html.escape(image_rel)}" alt="{html.escape(asset.asset_id)}">' if image_rel else '<div class="placeholder">IMAGE PENDING</div>'}
          <p><strong>Shots:</strong> {html.escape(', '.join(asset.linked_shots))}</p>
          <p><strong>Full narration:</strong> {html.escape(full_narration)}</p>
          <p><strong>Image prompt:</strong></p><pre>{html.escape(asset.image_prompt)}</pre>
          <p><strong>Video prompt:</strong></p><pre>{html.escape(asset.video_prompt)}</pre>
        </article>
        """)
    html_doc = f"""<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(brief.title)} contact sheet</title>
    <style>body{{font-family:Arial,sans-serif;background:#07131c;color:#dbe7ea;margin:30px}}main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:24px}}article{{background:#0d2532;padding:20px;border:1px solid #315363;border-radius:12px}}img{{width:100%;aspect-ratio:16/9;object-fit:cover}}pre{{white-space:pre-wrap;background:#081820;padding:12px}}.placeholder{{aspect-ratio:16/9;display:grid;place-items:center;background:#122f3d;color:#78909a}}</style></head>
    <body><h1>{html.escape(brief.title)} — Master Footage Contact Sheet</h1><main>{''.join(cards)}</main></body></html>"""
    html_path = out_dir / "contact_sheet.html"
    html_path.write_text(html_doc, encoding="utf-8")
    return {"png": str(png_path), "pdf": str(pdf_path), "html": str(html_path)}
