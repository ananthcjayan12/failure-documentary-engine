import pytest

from fde.models import Shot, ShotPlan
from fde.pipeline import _apply_visual_direction


def _shot(shot_id: str, start: float, end: float, visual: str) -> Shot:
    return Shot(
        shot_id=shot_id,
        chapter_id="CH01",
        narration_ids=["paragraph_01"],
        start=start,
        end=end,
        duration=end - start,
        narration_text="The exact spoken words.",
        visual_purpose=visual,
        visual_type="generated_image",
        suggested_visual=visual,
        image_prompt=f"image {visual}",
        video_prompt=f"video {visual}",
        sound_hint="quiet ambience",
    )


def test_visual_director_changes_creative_fields_but_not_master_clock():
    exact = ShotPlan(
        project_id="demo",
        total_seconds=8,
        voiceover_sha256="voice-hash",
        shots=[_shot("SHOT_001", 0, 4, "exact one"), _shot("SHOT_002", 4, 8, "exact two")],
    )
    proposed = ShotPlan(
        project_id="demo",
        total_seconds=999,
        voiceover_sha256="wrong-hash",
        shots=[_shot("SHOT_001", 10, 20, "directed one"), _shot("SHOT_002", 20, 40, "directed two")],
    )

    result = _apply_visual_direction(exact, proposed)

    assert result.total_seconds == 8
    assert result.voiceover_sha256 == "voice-hash"
    assert [(shot.start, shot.end, shot.duration) for shot in result.shots] == [(0, 4, 4), (4, 8, 4)]
    assert [shot.narration_text for shot in result.shots] == ["The exact spoken words."] * 2
    assert [shot.visual_purpose for shot in result.shots] == ["directed one", "directed two"]
    assert [shot.image_prompt for shot in result.shots] == ["image directed one", "image directed two"]


def test_visual_director_cannot_drop_or_reorder_shots():
    exact = ShotPlan(
        project_id="demo", total_seconds=8, voiceover_sha256="voice-hash",
        shots=[_shot("SHOT_001", 0, 4, "one"), _shot("SHOT_002", 4, 8, "two")],
    )
    missing = ShotPlan(
        project_id="demo", total_seconds=8, voiceover_sha256="voice-hash",
        shots=[_shot("SHOT_002", 4, 8, "two")],
    )
    with pytest.raises(RuntimeError, match="every immutable shot ID"):
        _apply_visual_direction(exact, missing)
