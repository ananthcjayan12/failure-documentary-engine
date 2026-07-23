from __future__ import annotations

from pathlib import Path

from .constants import DEFAULT_GLOBAL_STYLE
from .io import load_model, write_json
from .models import AudioTiming, DocumentaryScript, Shot, ShotPlan
from .narration import clean_spoken_text
from .timing import timing_is_current


def _script(project_dir: Path) -> DocumentaryScript:
    path = project_dir / "03_narration/narration.json"
    if not path.exists():
        path = project_dir / "03_script/script.json"
    return load_model(path, DocumentaryScript)


def _candidate_boundaries(timing: AudioTiming) -> list[tuple[float, float]]:
    words = timing.words
    candidates: list[tuple[float, float]] = []
    for previous, following in zip(words, words[1:]):
        boundary = following.start
        gap = max(0.0, following.start - previous.end)
        candidates.append((boundary, gap))
    for paragraph in timing.paragraphs[:-1]:
        candidates.append((paragraph.end, 0.5))
    return sorted({(round(at, 3), round(gap, 3)) for at, gap in candidates})


def _boundaries(
    timing: AudioTiming,
    *,
    minimum: float = 3.0,
    target: float = 6.0,
    maximum: float = 10.0,
) -> list[float]:
    end = timing.audio_duration_seconds
    candidates = _candidate_boundaries(timing)
    result = [0.0]
    cursor = 0.0
    while end - cursor > maximum:
        eligible = [(at, gap) for at, gap in candidates if cursor + minimum <= at <= cursor + maximum]
        if eligible:
            desired = cursor + target
            chosen = min(eligible, key=lambda item: (abs(item[0] - desired) - min(item[1], 0.7) * 2.0, item[0]))[0]
        else:
            chosen = min(end, cursor + maximum)
        if chosen <= cursor + 0.001:
            break
        result.append(round(chosen, 3))
        cursor = chosen
    # Do not merge a short tail back into the previous shot when doing so
    # would exceed the source-video duration.  A 3–4 second tail is valid;
    # an overlong shot cannot be rendered from the five-second master clip.
    if end - result[-1] < minimum and len(result) > 1:
        merged_duration = end - result[-2]
        if merged_duration <= maximum + 0.001:
            result.pop()
    result.append(round(end, 3))
    return result


def _shot_text(timing: AudioTiming, start: float, end: float) -> tuple[str, list[str]]:
    selected = [item for item in timing.words if item.start < end and item.end > start]
    paragraph_ids = list(dict.fromkeys(item.paragraph_id for item in selected))
    return " ".join(item.word for item in selected), paragraph_ids


def plan_shots(
    project_dir: Path,
    *,
    minimum: float = 3.0,
    target: float = 4.5,
    maximum: float = 5.0,
) -> ShotPlan:
    project_dir = Path(project_dir)
    if not timing_is_current(project_dir):
        raise RuntimeError("current voice timing is required before shot planning")
    timing = load_model(project_dir / "05_timing/audio_timing.json", AudioTiming)
    script = _script(project_dir)
    chapter_by_paragraph = {item.narration_id: item.chapter_id for item in script.segments}
    points = _boundaries(timing, minimum=minimum, target=target, maximum=maximum)
    shots: list[Shot] = []
    for index, (start, end) in enumerate(zip(points, points[1:]), start=1):
        narration_text, paragraph_ids = _shot_text(timing, start, end)
        chapter_id = chapter_by_paragraph.get(paragraph_ids[0], "") if paragraph_ids else ""
        visual = f"A technically credible documentary visual that clearly supports this narration: {narration_text}"
        shot_id = f"SHOT_{index:03d}"
        shots.append(
            Shot(
                shot_id=shot_id,
                chapter_id=chapter_id,
                narration_ids=paragraph_ids,
                start=start,
                end=end,
                duration=end - start,
                narration_text=narration_text,
                visual_purpose="Support the exact spoken beat without adding unsupported facts.",
                visual_type="generated_image",
                suggested_visual=visual,
                image_prompt=(
                    f"{DEFAULT_GLOBAL_STYLE}\n\nSHOT {shot_id}\n{visual}\n"
                    "Frame the scene for a 16:9 documentary composition. Preserve realistic geometry and leave clean negative space."
                ),
                video_prompt=(
                    "Animate the approved source image with restrained, physically credible movement. "
                    "Preserve identity, geometry, lighting, weather and composition. Use subtle camera motion only; no morphing or new objects."
                ),
                sound_hint="subtle location-appropriate ambience; keep narration fully intelligible",
                transition="hard_cut",
                camera="restrained cinematic framing",
                motion="subtle controlled movement",
            )
        )
    plan = ShotPlan(
        project_id=script.project_id,
        shots=shots,
        total_seconds=timing.audio_duration_seconds,
        voiceover_sha256=timing.voiceover_sha256,
    )
    root = project_dir / "06_shots"
    write_json(root / "shot_plan.json", plan)
    # Keep a compatibility mirror for existing review/report helpers.
    write_json(project_dir / "04_shot_plan/shot_plan.json", plan)
    return plan
