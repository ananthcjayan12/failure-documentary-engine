from __future__ import annotations

from collections import Counter

import pytest

from fde.compact_planning import (
    AssignmentBatch,
    CompactShotIndex,
    MasterVocabularyOutline,
    _combine_plan,
    _score_candidates,
    build_compact_shot_index,
    deterministic_details,
    deterministic_outline,
    semantic_boundaries,
    validate_detail_batch,
    validate_outline,
    validate_response_envelope,
)
from fde.models import (
    AudioTiming,
    DocumentaryScript,
    MasterFootageStrategy,
    NarrationSegment,
    ProjectBrief,
    ShotSkeleton,
    ShotSkeletonPlan,
    WordTiming,
    ParagraphTiming,
)


def _semantic_fixture() -> tuple[AudioTiming, DocumentaryScript]:
    sentences = [
        "The aircraft departed under normal conditions.",
        "Minutes later the first signal disappeared.",
        "Investigators compared radar and satellite evidence.",
        "The final route remained uncertain.",
    ]
    text = " ".join(sentences)
    tokens = text.replace(".", "").split()
    words = [
        WordTiming(
            index=index,
            paragraph_id="paragraph_01",
            word=token,
            start=float(index),
            end=float(index) + 0.72,
        )
        for index, token in enumerate(tokens)
    ]
    duration = float(len(tokens))
    timing = AudioTiming(
        project_id="semantic",
        source="test",
        exact=True,
        voiceover_sha256="voice",
        audio_duration_seconds=duration,
        paragraphs=[
            ParagraphTiming(
                paragraph_id="paragraph_01",
                start=0,
                end=duration,
                duration=duration,
            )
        ],
        words=words,
    )
    script = DocumentaryScript(
        project_id="semantic",
        title="Semantic",
        segments=[
            NarrationSegment(
                narration_id="paragraph_01",
                chapter_id="CH01",
                text=text,
                estimated_duration=duration,
                claim_ids=["CLM_001"],
            )
        ],
    )
    return timing, script


def _skeleton(count: int = 36) -> ShotSkeletonPlan:
    shots = []
    functions = [
        "physical_story_moment",
        "evidence_explanation",
        "narrative_progression",
        "question_or_mystery",
    ]
    for index in range(count):
        start = index * 6.0
        story_function = functions[index % len(functions)]
        shots.append(
            ShotSkeleton(
                shot_id=f"SHOT_{index + 1:03d}",
                chapter_id=f"CH{index // 6 + 1:02d}",
                narration_ids=[f"paragraph_{index + 1:02d}"],
                claim_ids=[f"CLM_{index + 1:03d}"],
                start=start,
                end=start + 6,
                duration=6,
                narration_text=(
                    f"Investigators explain evidence beat {index + 1} without changing "
                    "the approved factual record."
                ),
                visual_purpose="technical_explanation",
                story_function=story_function,
                factual_scope=[f"CLM_{index + 1:03d}"],
            )
        )
    return ShotSkeletonPlan(
        project_id="compact",
        shots=shots,
        total_seconds=count * 6,
        voiceover_sha256="voice-sha",
    )


def test_semantic_segmentation_is_not_a_five_second_media_grid():
    timing, script = _semantic_fixture()
    boundaries = semantic_boundaries(timing, script)
    durations = [end - start for start, end in zip(boundaries, boundaries[1:])]
    assert max(durations) <= 12.0
    assert any(duration > 5.0 for duration in durations)
    assert len(durations) < timing.audio_duration_seconds / 5.0


def test_compact_index_excludes_verbose_generation_and_timeline_fields():
    compact = build_compact_shot_index(_skeleton(10))
    payload = compact.model_dump(mode="json")
    assert len(payload["shots"]) == 10
    assert all(len(item["narration_summary"].split()) <= 28 for item in payload["shots"])
    forbidden = {
        "narration_text",
        "image_prompt",
        "video_prompt",
        "camera",
        "motion",
        "media_jobs",
    }
    assert not forbidden.intersection(payload["shots"][0])


def test_global_outline_and_three_detail_batches_build_exact_vocabulary():
    skeleton = _skeleton()
    compact = build_compact_shot_index(skeleton)
    strategy = MasterFootageStrategy()
    outline = deterministic_outline(compact, strategy)
    validate_outline(outline, compact, strategy)
    assert isinstance(outline, MasterVocabularyOutline)
    assert len(outline.packages) == 24
    assert Counter(item.category for item in outline.packages) == {
        "hero": 8,
        "atmosphere": 8,
        "investigation": 8,
    }
    assert {
        shot_id
        for package in outline.packages
        for shot_id in package.supported_shot_ids
    } == {item.shot_id for item in compact.shots}

    batches = []
    for category in ("hero", "atmosphere", "investigation"):
        requested = [item for item in outline.packages if item.category == category]
        batch = deterministic_details(category, requested)
        validate_detail_batch(batch, requested)
        assert len(batch.packages) == 8
        batches.append(batch)

    brief = ProjectBrief(
        project_id="compact",
        title="Compact",
        topic="Test",
        maximum_master_assets=24,
    )
    plan = _combine_plan(
        outline,
        batches,
        brief=brief,
        skeleton=skeleton,
        version=1,
    )
    plan.status = "approved"
    candidate_sets, local, ambiguous = _score_candidates(compact, plan)
    assert len(candidate_sets) == len(skeleton.shots)
    assert len(local) + len(ambiguous) == len(skeleton.shots)
    assert all(len(item.candidates) <= 3 for item in candidate_sets)


def test_model_error_envelope_is_rejected_before_pydantic_validation():
    with pytest.raises(RuntimeError, match="Unable to return"):
        validate_response_envelope(
            {"error": "Unable to return a valid assignment contract."},
            AssignmentBatch,
        )
    with pytest.raises(RuntimeError, match="missing required field"):
        validate_response_envelope({}, AssignmentBatch)
