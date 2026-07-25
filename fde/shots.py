from __future__ import annotations

from pathlib import Path

from .io import load_model, write_json
from .models import (
    AudioTiming,
    DocumentaryScript,
    ShotSkeleton,
    ShotSkeletonPlan,
)
from .timing import timing_is_current


def _script(project_dir: Path) -> DocumentaryScript:
    path = project_dir / "03_narration/narration.json"
    if not path.exists():
        path = project_dir / "03_script/script.json"
    return load_model(path, DocumentaryScript)


def _candidate_boundaries(timing: AudioTiming) -> list[tuple[float, float]]:
    candidates: list[tuple[float, float]] = []
    for previous, following in zip(timing.words, timing.words[1:]):
        candidates.append((following.start, max(0.0, following.start - previous.end)))
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
            chosen = min(
                eligible,
                key=lambda item: (
                    abs(item[0] - desired) - min(item[1], 0.7) * 2.0,
                    item[0],
                ),
            )[0]
        else:
            chosen = min(end, cursor + maximum)
        if chosen <= cursor + 0.001:
            break
        result.append(round(chosen, 3))
        cursor = chosen
    if end - result[-1] < minimum and len(result) > 1:
        result.pop()
    result.append(round(end, 3))
    return result


def _shot_text(timing: AudioTiming, start: float, end: float) -> tuple[str, list[str]]:
    selected = [item for item in timing.words if item.start < end and item.end > start]
    paragraph_ids = list(dict.fromkeys(item.paragraph_id for item in selected))
    return " ".join(item.word for item in selected), paragraph_ids


def _story_function(index: int, total: int, chapter_id: str) -> str:
    if index == 1:
        return "cold_open"
    if index == total:
        return "human_resolution"
    lowered = chapter_id.lower()
    if any(value in lowered for value in ("evidence", "search", "investigation")):
        return "evidence_explanation"
    if any(value in lowered for value in ("warning", "critical", "failure")):
        return "physical_story_moment"
    return "narrative_progression"


def plan_shot_skeleton(
    project_dir: Path,
    *,
    minimum: float = 3.0,
    target: float = 6.0,
    maximum: float = 10.0,
) -> ShotSkeletonPlan:
    """Compile immutable shot timing from the approved voiceover.

    This stage deliberately contains no image prompts, video prompts, crop choices,
    or master-asset assignments. Those belong to the later two-pass visual system.
    """
    project_dir = Path(project_dir)
    if not timing_is_current(project_dir):
        raise RuntimeError("current voice timing is required before shot-skeleton planning")
    timing = load_model(project_dir / "05_timing/audio_timing.json", AudioTiming)
    script = _script(project_dir)
    segment_by_id = {item.narration_id: item for item in script.segments}
    points = _boundaries(timing, minimum=minimum, target=target, maximum=maximum)
    skeletons: list[ShotSkeleton] = []
    total = len(points) - 1
    for index, (start, end) in enumerate(zip(points, points[1:]), start=1):
        narration_text, paragraph_ids = _shot_text(timing, start, end)
        segments = [segment_by_id[item] for item in paragraph_ids if item in segment_by_id]
        chapter_id = segments[0].chapter_id if segments else ""
        claim_ids = list(dict.fromkeys(claim for segment in segments for claim in segment.claim_ids))
        skeletons.append(
            ShotSkeleton(
                shot_id=f"SHOT_{index:03d}",
                chapter_id=chapter_id,
                narration_ids=paragraph_ids,
                claim_ids=claim_ids,
                start=start,
                end=end,
                duration=end - start,
                narration_text=narration_text,
                visual_purpose=(
                    "Represent the factual meaning of this spoken beat without adding "
                    "unsupported events, locations, damage, evidence, or people."
                ),
                story_function=_story_function(index, total, chapter_id),
                factual_scope=claim_ids,
            )
        )
    plan = ShotSkeletonPlan(
        project_id=script.project_id,
        shots=skeletons,
        total_seconds=timing.audio_duration_seconds,
        voiceover_sha256=timing.voiceover_sha256,
        timing_source=timing.source,
    )
    root = project_dir / "06_shots"
    write_json(root / "shot_skeleton.json", plan)

    return plan
