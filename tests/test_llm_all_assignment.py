from __future__ import annotations

from pathlib import Path

import pytest

from fde.compact_planning import (
    AssignmentBatch,
    AssignmentDecision,
    CompactShot,
    CompactShotIndex,
)
from fde.editorial import EditorialPlanValidationError
from fde.llm_editorial_assignment import (
    ASSIGNMENT_BATCH_SIZE,
    _validate_assignment_decision,
    assign_every_shot_with_llm,
    build_hard_eligibility,
)
from fde.models import CropRegion, MasterAsset, MasterAssetPlan


def _asset(
    asset_id: str,
    *,
    category: str = "atmosphere",
    claims: list[str] | None = None,
    linked: list[str] | None = None,
) -> MasterAsset:
    return MasterAsset(
        asset_id=asset_id,
        title=f"Asset {asset_id}",
        category=category,
        linked_shots=linked or [],
        primary_use="Reusable approved visual context",
        factual_scope=claims or [],
        factual_context_id="CH01",
        allowed_operations=["full_frame", "crop", "freeze", "callback", "loop"],
        crop_regions=[CropRegion(crop_id="wide", description="Approved wide crop")],
        loopable=category == "atmosphere",
        reconstruction_disclosure=(
            {"required": True} if category == "investigation" else None
        ),
        reuse_rationale="Approved reusable package.",
    )


def _compact(count: int, *, claims: bool = False) -> CompactShotIndex:
    shots = []
    for index in range(count):
        start = index * 6.0
        shots.append(
            CompactShot(
                shot_id=f"SHOT_{index + 1:03d}",
                chapter_id="CH01",
                start=start,
                end=start + 6,
                duration=6,
                narration_summary=f"Narration beat {index + 1}",
                claim_ids=["CLM_001"] if claims else [],
                visual_need="narrative_support",
                story_function="narrative_progression",
                importance="medium",
            )
        )
    return CompactShotIndex(
        project_id="all-llm",
        voiceover_sha256="voice",
        total_seconds=count * 6,
        shots=shots,
    )


def _plan(assets: list[MasterAsset]) -> MasterAssetPlan:
    return MasterAssetPlan(
        project_id="all-llm",
        maximum_assets=len(assets),
        plan_version=3,
        status="approved",
        assets=assets,
    )


def test_hard_eligibility_does_not_score_or_rank_candidates():
    compact = _compact(1, claims=True)
    plan = _plan(
        [
            _asset("H01", category="hero", claims=["CLM_001"], linked=["SHOT_001"]),
            _asset("L01", category="atmosphere", claims=[]),
            _asset("E01", category="investigation", claims=["CLM_999"]),
        ]
    )
    eligibility = build_hard_eligibility(compact, plan)
    row = eligibility.shots[0]
    assert [item.asset_id for item in row.eligible_assets] == ["H01", "L01"]
    assert "E01" in row.excluded_assets
    payload = row.model_dump(mode="json")
    assert "score" not in str(payload).lower()
    assert "confidence" not in str(payload).lower()
    assert payload["eligible_assets"][1]["linked_by_vocabulary_outline"] is False


def test_every_production_shot_is_sent_to_llm_in_compact_batches_and_cached(tmp_path: Path):
    compact = _compact(25)
    plan = _plan([_asset("H01", category="hero"), _asset("L01")])
    eligibility = build_hard_eligibility(compact, plan)
    expected_batches = [
        compact.shots[index : index + ASSIGNMENT_BATCH_SIZE]
        for index in range(0, len(compact.shots), ASSIGNMENT_BATCH_SIZE)
    ]

    class FakeAgent:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, **kwargs):
            batch = expected_batches[self.calls]
            self.calls += 1
            return AssignmentBatch(
                assignments=[
                    AssignmentDecision(
                        shot_id=shot.shot_id,
                        asset_id="H01" if index % 2 == 0 else "L01",
                        reuse_operation="full_frame",
                        crop_id="wide",
                        playback_speed=1.0,
                        source_in=0,
                        source_out=5,
                        support_reason="LLM selected the strongest sequence-aware option.",
                        confidence=0.9,
                    )
                    for index, shot in enumerate(batch)
                ]
            )

    fake = FakeAgent()

    def factory(kind, context, consume_response):
        assert kind == "routed"
        return fake

    decisions, stats = assign_every_shot_with_llm(
        project=tmp_path,
        project_id="all-llm",
        title="All LLM",
        compact=compact,
        master_plan=plan,
        eligibility_plan=eligibility,
        agent_kind="routed",
        consume_response=False,
        agent_factory=factory,
    )
    assert len(decisions) == 25
    assert fake.calls == 3
    assert stats == {
        "assignment_shot_count": 25,
        "batch_count": 3,
        "model_calls": 3,
        "cache_hits": 0,
    }

    def no_model_calls(*args, **kwargs):
        raise AssertionError("valid assignment batches should be reused from cache")

    cached_decisions, cached_stats = assign_every_shot_with_llm(
        project=tmp_path,
        project_id="all-llm",
        title="All LLM",
        compact=compact,
        master_plan=plan,
        eligibility_plan=eligibility,
        agent_kind="routed",
        consume_response=False,
        agent_factory=no_model_calls,
    )
    assert cached_decisions.keys() == decisions.keys()
    assert cached_stats["model_calls"] == 0
    assert cached_stats["cache_hits"] == 3


def test_assignment_llm_cannot_escape_objective_eligibility_set():
    compact = _compact(1, claims=True)
    plan = _plan(
        [
            _asset("H01", category="hero", claims=["CLM_001"]),
            _asset("E01", category="investigation", claims=["CLM_999"]),
        ]
    )
    eligibility = build_hard_eligibility(compact, plan).shots[0]
    with pytest.raises(EditorialPlanValidationError, match="eligibility set"):
        _validate_assignment_decision(
            AssignmentDecision(
                shot_id="SHOT_001",
                asset_id="E01",
                crop_id="wide",
                source_out=5,
                support_reason="Invalid choice",
            ),
            shot=compact.shots[0],
            eligibility=eligibility,
            assets={item.asset_id: item for item in plan.assets},
        )
