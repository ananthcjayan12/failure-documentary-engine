from __future__ import annotations

from .models import ShotPlan
from . import pipeline as _pipeline


def _apply_visual_direction(exact: ShotPlan, proposed: ShotPlan) -> ShotPlan:
    """Legacy contract used by old projects and tests.

    New production uses EditorialShotPlan, but old visual-director responses still
    receive the same protection: creative fields may change while timing, narration,
    project ID, total duration, and voice hash remain immutable.
    """
    expected = [item.shot_id for item in exact.shots]
    actual = [item.shot_id for item in proposed.shots]
    if actual != expected:
        raise RuntimeError("visual director must return every immutable shot ID in original order")
    proposed_by_id = {item.shot_id: item for item in proposed.shots}
    shots = []
    for source in exact.shots:
        directed = proposed_by_id[source.shot_id].model_copy(deep=True)
        directed.shot_id = source.shot_id
        directed.chapter_id = source.chapter_id
        directed.narration_ids = list(source.narration_ids)
        directed.claim_ids = list(source.claim_ids)
        directed.start = source.start
        directed.end = source.end
        directed.duration = source.duration
        directed.narration_text = source.narration_text
        shots.append(directed)
    return ShotPlan(
        project_id=exact.project_id,
        shots=shots,
        total_seconds=exact.total_seconds,
        voiceover_sha256=exact.voiceover_sha256,
    )


_pipeline._apply_visual_direction = _apply_visual_direction
