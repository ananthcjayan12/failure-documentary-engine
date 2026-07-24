from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from .agents import get_agent
from .compact_planning import (
    AssignmentBatch,
    AssignmentDecision,
    CompactShot,
    CompactShotIndex,
    build_compact_shot_index,
)
from .editorial import EditorialPlanValidationError, validate_editorial_plan
from .io import load_model, read_json, versioned_path, write_json
from .master_footage import approved_master_plan
from .models import (
    EditorialShot,
    EditorialShotPlan,
    MasterAsset,
    MasterAssetPlan,
    OverlaySpec,
    ProjectState,
    Shot,
    ShotPlan,
    ShotSkeletonPlan,
)
from .project import ProjectStore
from .prompts import render_prompt


ASSIGNMENT_BATCH_SIZE = 12
CONTEXT_ASSIGNMENT_COUNT = 4
LOOKAHEAD_SHOT_COUNT = 4


class EligibleAssetRef(BaseModel):
    asset_id: str
    category: str
    linked_by_vocabulary_outline: bool = False
    factual_basis: Literal[
        "explicit_outline_link",
        "claim_scope_compatible",
        "unscoped_context",
    ]
    allowed_operations: list[str] = Field(default_factory=list)
    crop_ids: list[str] = Field(default_factory=list)


class ShotEligibility(BaseModel):
    shot_id: str
    eligible_assets: list[EligibleAssetRef]
    excluded_assets: dict[str, list[str]] = Field(default_factory=dict)


class AssignmentEligibilityPlan(BaseModel):
    project_id: str
    voiceover_sha256: str
    master_plan_version: int
    shots: list[ShotEligibility]
    policy: str = (
        "Local code performs objective hard eligibility checks only. "
        "It does not score, rank, or make production creative assignments."
    )


def _hard_exclusion_reasons(shot: CompactShot, asset: MasterAsset) -> list[str]:
    """Return only objective reasons why an asset cannot safely serve a shot."""
    reasons: list[str] = []
    if not asset.allowed_operations:
        reasons.append("asset_has_no_allowed_reuse_operations")
    if asset.source_duration_seconds <= 0:
        reasons.append("asset_has_invalid_source_duration")
    if asset.playback_speed_min <= 0 or asset.playback_speed_max < asset.playback_speed_min:
        reasons.append("asset_has_invalid_playback_range")
    if not asset.crop_regions:
        reasons.append("asset_has_no_approved_crop_regions")

    shot_claims = set(shot.claim_ids)
    asset_claims = set(asset.factual_scope)
    explicitly_linked = shot.shot_id in asset.linked_shots

    if explicitly_linked:
        return reasons

    if shot_claims and asset.category == "investigation":
        missing = sorted(shot_claims - asset_claims)
        if missing:
            reasons.append(
                "investigation_factual_scope_missing:" + ",".join(missing)
            )
    elif shot_claims and asset_claims and not (shot_claims & asset_claims):
        reasons.append("asset_factual_scope_is_disjoint_from_shot_claims")

    return reasons


def build_hard_eligibility(
    compact: CompactShotIndex,
    master_plan: MasterAssetPlan,
    *,
    excluded_shot_ids: set[str] | None = None,
) -> AssignmentEligibilityPlan:
    """Build unranked candidate sets from approved assets.

    This function deliberately has no weights, similarity score, confidence,
    category preference, usage balancing, or adjacent-repetition heuristic.
    """
    excluded_shot_ids = excluded_shot_ids or set()
    rows: list[ShotEligibility] = []
    for shot in compact.shots:
        if shot.shot_id in excluded_shot_ids:
            continue
        eligible: list[EligibleAssetRef] = []
        excluded: dict[str, list[str]] = {}
        for asset in master_plan.assets:
            reasons = _hard_exclusion_reasons(shot, asset)
            if reasons:
                excluded[asset.asset_id] = reasons
                continue
            explicitly_linked = shot.shot_id in asset.linked_shots
            if explicitly_linked:
                factual_basis = "explicit_outline_link"
            elif shot.claim_ids and asset.factual_scope:
                factual_basis = "claim_scope_compatible"
            else:
                factual_basis = "unscoped_context"
            eligible.append(
                EligibleAssetRef(
                    asset_id=asset.asset_id,
                    category=asset.category,
                    linked_by_vocabulary_outline=explicitly_linked,
                    factual_basis=factual_basis,
                    allowed_operations=list(asset.allowed_operations),
                    crop_ids=[item.crop_id for item in asset.crop_regions],
                )
            )
        if not eligible:
            details = "; ".join(
                f"{asset_id}={','.join(reasons)}"
                for asset_id, reasons in excluded.items()
            )
            raise EditorialPlanValidationError(
                f"{shot.shot_id} has no objectively eligible approved asset. {details}"
            )
        rows.append(
            ShotEligibility(
                shot_id=shot.shot_id,
                eligible_assets=eligible,
                excluded_assets=excluded,
            )
        )
    return AssignmentEligibilityPlan(
        project_id=compact.project_id,
        voiceover_sha256=compact.voiceover_sha256,
        master_plan_version=master_plan.plan_version,
        shots=rows,
    )


def _asset_registry(
    master_plan: MasterAssetPlan,
    asset_ids: set[str],
) -> list[dict[str, Any]]:
    return [
        {
            "asset_id": asset.asset_id,
            "category": asset.category,
            "title": asset.title,
            "primary_use": asset.primary_use,
            "secondary_uses": asset.secondary_uses,
            "factual_scope": asset.factual_scope,
            "factual_context_id": asset.factual_context_id,
            "continuity_requirements": asset.continuity_requirements,
            "prohibited_details": asset.prohibited_details,
            "loopable": asset.loopable,
            "major_story_moment": asset.major_story_moment,
            "allowed_operations": asset.allowed_operations,
            "crop_ids": [item.crop_id for item in asset.crop_regions],
            "overlay_safe_zones": asset.overlay_safe_zones,
            "supported_overlay_families": asset.supported_overlay_families,
            "source_duration_seconds": asset.source_duration_seconds,
            "playback_speed_min": asset.playback_speed_min,
            "playback_speed_max": asset.playback_speed_max,
            "reconstruction_disclosure_required": bool(
                asset.reconstruction_disclosure
                and asset.reconstruction_disclosure.required
            ),
        }
        for asset in master_plan.assets
        if asset.asset_id in asset_ids
    ]


def _batch_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_assignment_decision(
    decision: AssignmentDecision,
    *,
    shot: CompactShot,
    eligibility: ShotEligibility,
    assets: dict[str, MasterAsset],
) -> None:
    if decision.shot_id != shot.shot_id:
        raise EditorialPlanValidationError(
            f"Assignment returned {decision.shot_id} for requested {shot.shot_id}."
        )
    eligible_ids = {item.asset_id for item in eligibility.eligible_assets}
    if decision.asset_id not in eligible_ids:
        raise EditorialPlanValidationError(
            f"{shot.shot_id} selected {decision.asset_id}, which is not in its "
            "objective eligibility set."
        )
    asset = assets[decision.asset_id]
    operation = (
        "loop"
        if decision.reuse_operation == "loop_and_slow"
        else decision.reuse_operation
    )
    if operation not in asset.allowed_operations:
        raise EditorialPlanValidationError(
            f"{shot.shot_id} uses unsupported operation "
            f"{decision.reuse_operation} on {asset.asset_id}."
        )
    crop_ids = {item.crop_id for item in asset.crop_regions}
    if decision.crop_id and decision.crop_id not in crop_ids:
        raise EditorialPlanValidationError(
            f"{shot.shot_id} uses unknown crop {decision.crop_id} "
            f"on {asset.asset_id}."
        )
    if not (
        asset.playback_speed_min
        <= decision.playback_speed
        <= asset.playback_speed_max
    ):
        raise EditorialPlanValidationError(
            f"{shot.shot_id} playback speed is outside "
            f"{asset.asset_id}'s approved range."
        )
    source_out = decision.source_out or asset.source_duration_seconds
    if (
        decision.source_in >= source_out
        or source_out > asset.source_duration_seconds + 0.01
    ):
        raise EditorialPlanValidationError(
            f"{shot.shot_id} returned an invalid source range "
            f"for {asset.asset_id}."
        )
    if decision.overlay_type:
        if decision.overlay_type not in asset.supported_overlay_families:
            raise EditorialPlanValidationError(
                f"{shot.shot_id} selected unsupported overlay "
                f"{decision.overlay_type} on {asset.asset_id}."
            )
    if not decision.support_reason.strip():
        raise EditorialPlanValidationError(
            f"{shot.shot_id} has no editorial support reason."
        )


def _validate_batch(
    response: AssignmentBatch,
    *,
    batch_shots: list[CompactShot],
    eligibility_by_shot: dict[str, ShotEligibility],
    assets: dict[str, MasterAsset],
) -> dict[str, AssignmentDecision]:
    expected_ids = [item.shot_id for item in batch_shots]
    actual_ids = [item.shot_id for item in response.assignments]
    if actual_ids != expected_ids:
        raise EditorialPlanValidationError(
            "Assignment batch must return every requested shot exactly once "
            f"in original order. expected={expected_ids}; actual={actual_ids}"
        )
    result: dict[str, AssignmentDecision] = {}
    for shot, decision in zip(batch_shots, response.assignments):
        _validate_assignment_decision(
            decision,
            shot=shot,
            eligibility=eligibility_by_shot[shot.shot_id],
            assets=assets,
        )
        result[shot.shot_id] = decision
    return result


def _cached_batch(
    path: Path,
    *,
    input_hash: str,
    batch_shots: list[CompactShot],
    eligibility_by_shot: dict[str, ShotEligibility],
    assets: dict[str, MasterAsset],
) -> dict[str, AssignmentDecision] | None:
    if not path.exists():
        return None
    try:
        payload = read_json(path)
        if payload.get("input_hash") != input_hash:
            return None
        response = AssignmentBatch.model_validate(payload.get("response", {}))
        return _validate_batch(
            response,
            batch_shots=batch_shots,
            eligibility_by_shot=eligibility_by_shot,
            assets=assets,
        )
    except Exception:
        return None


def _assignment_context(
    decisions: dict[str, AssignmentDecision],
    ordered_shot_ids: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for shot_id in ordered_shot_ids:
        decision = decisions.get(shot_id)
        if decision is None:
            continue
        rows.append(
            {
                "shot_id": shot_id,
                "asset_id": decision.asset_id,
                "reuse_operation": decision.reuse_operation,
                "crop_id": decision.crop_id,
            }
        )
    return rows[-CONTEXT_ASSIGNMENT_COUNT:]


def assign_every_shot_with_llm(
    *,
    project: Path,
    project_id: str,
    title: str,
    compact: CompactShotIndex,
    master_plan: MasterAssetPlan,
    eligibility_plan: AssignmentEligibilityPlan,
    agent_kind: str,
    consume_response: bool,
    agent_factory: Callable[..., Any] = get_agent,
) -> tuple[dict[str, AssignmentDecision], dict[str, int]]:
    """Assign every generated-media shot through compact LLM batches."""
    eligibility_by_shot = {
        item.shot_id: item for item in eligibility_plan.shots
    }
    assignment_shots = [
        item for item in compact.shots if item.shot_id in eligibility_by_shot
    ]
    assets = {item.asset_id: item for item in master_plan.assets}
    ordered_ids = [item.shot_id for item in assignment_shots]
    decisions: dict[str, AssignmentDecision] = {}
    model_calls = 0
    cache_hits = 0

    for batch_number, start in enumerate(
        range(0, len(assignment_shots), ASSIGNMENT_BATCH_SIZE),
        start=1,
    ):
        batch_shots = assignment_shots[start : start + ASSIGNMENT_BATCH_SIZE]
        batch_eligibility = [
            eligibility_by_shot[item.shot_id] for item in batch_shots
        ]
        relevant_asset_ids = {
            asset.asset_id
            for row in batch_eligibility
            for asset in row.eligible_assets
        }
        registry = _asset_registry(master_plan, relevant_asset_ids)
        previous_context = _assignment_context(decisions, ordered_ids[:start])
        lookahead = assignment_shots[
            start + ASSIGNMENT_BATCH_SIZE :
            start + ASSIGNMENT_BATCH_SIZE + LOOKAHEAD_SHOT_COUNT
        ]
        payload = {
            "project_id": project_id,
            "voiceover_sha256": compact.voiceover_sha256,
            "master_plan_version": master_plan.plan_version,
            "batch_number": batch_number,
            "shots": [item.model_dump(mode="json") for item in batch_shots],
            "eligibility": [
                item.model_dump(mode="json") for item in batch_eligibility
            ],
            "approved_assets": registry,
            "previous_assignments": previous_context,
            "lookahead_shots": [
                item.model_dump(mode="json") for item in lookahead
            ],
        }
        input_hash = _batch_hash(payload)
        cache_path = (
            project
            / "06_shots"
            / f"editorial_assignment_all_batch_{batch_number:02d}.json"
        )
        cached = _cached_batch(
            cache_path,
            input_hash=input_hash,
            batch_shots=batch_shots,
            eligibility_by_shot=eligibility_by_shot,
            assets=assets,
        )
        if cached is not None:
            decisions.update(cached)
            cache_hits += 1
            continue

        context = {
            "project_id": project_id,
            "title": title,
            "duration": compact.total_seconds,
        }
        agent = agent_factory(agent_kind, context, consume_response)
        response = agent.run(
            stage=f"editorial_assignment_all_batch_{batch_number:02d}",
            prompt=render_prompt(
                "editorial_assignment_all",
                batch_number=batch_number,
                batch_count=math.ceil(
                    len(assignment_shots) / ASSIGNMENT_BATCH_SIZE
                ),
                approved_assets=registry,
                compact_shots=batch_shots,
                eligibility=batch_eligibility,
                previous_assignments=previous_context,
                lookahead_shots=lookahead,
            ),
            output_model=AssignmentBatch,
            request_dir=project / "_requests",
        )
        validated = _validate_batch(
            response,
            batch_shots=batch_shots,
            eligibility_by_shot=eligibility_by_shot,
            assets=assets,
        )
        decisions.update(validated)
        write_json(
            cache_path,
            {
                "input_hash": input_hash,
                "batch_number": batch_number,
                "response": response.model_dump(mode="json"),
            },
        )
        model_calls += 1

    return decisions, {
        "assignment_shot_count": len(assignment_shots),
        "batch_count": math.ceil(
            len(assignment_shots) / ASSIGNMENT_BATCH_SIZE
        ),
        "model_calls": model_calls,
        "cache_hits": cache_hits,
    }


def _test_only_decisions(
    compact: CompactShotIndex,
    eligibility_plan: AssignmentEligibilityPlan,
    master_plan: MasterAssetPlan,
) -> dict[str, AssignmentDecision]:
    """Offline deterministic substitute; never used by a production routed run."""
    assets = {item.asset_id: item for item in master_plan.assets}
    eligibility = {item.shot_id: item for item in eligibility_plan.shots}
    usage: dict[str, int] = defaultdict(int)
    previous_asset: str | None = None
    decisions: dict[str, AssignmentDecision] = {}

    for shot in compact.shots:
        row = eligibility.get(shot.shot_id)
        if row is None:
            continue
        ordered = sorted(
            row.eligible_assets,
            key=lambda item: (
                item.asset_id == previous_asset,
                usage[item.asset_id],
                item.asset_id,
            ),
        )
        asset = assets[ordered[0].asset_id]
        prior_usage = usage[asset.asset_id]
        if shot.duration > asset.source_duration_seconds and asset.loopable:
            operation = (
                "loop_and_slow"
                if "loop" in asset.allowed_operations
                and asset.playback_speed_min <= 0.8
                else "loop"
            )
            speed = max(asset.playback_speed_min, 0.8)
        elif shot.duration > asset.source_duration_seconds:
            operation = "freeze"
            speed = 1.0
        elif prior_usage:
            operation = "callback"
            speed = 1.0
        else:
            operation = "full_frame"
            speed = 1.0
        normalized_operation = (
            "loop" if operation == "loop_and_slow" else operation
        )
        if normalized_operation not in asset.allowed_operations:
            operation = asset.allowed_operations[0]
        crop_id = (
            asset.crop_regions[prior_usage % len(asset.crop_regions)].crop_id
            if asset.crop_regions
            else None
        )
        decisions[shot.shot_id] = AssignmentDecision(
            shot_id=shot.shot_id,
            asset_id=asset.asset_id,
            reuse_operation=operation,
            crop_id=crop_id,
            playback_speed=speed,
            source_in=0,
            source_out=asset.source_duration_seconds,
            visual_mode=(
                "master_video_freeze"
                if operation == "freeze"
                else "master_video"
            ),
            support_reason=(
                "Deterministic offline test assignment; production routed "
                "runs use an LLM for every generated-media shot."
            ),
            confidence=1.0,
        )
        usage[asset.asset_id] += 1
        previous_asset = asset.asset_id
    return decisions


def _build_plan(
    *,
    skeleton: ShotSkeletonPlan,
    master_plan: MasterAssetPlan,
    decisions: dict[str, AssignmentDecision],
) -> EditorialShotPlan:
    assets = {item.asset_id: item for item in master_plan.assets}
    exceptions = {
        item.shot_id: item for item in master_plan.non_generated_coverage
    }
    shots: list[EditorialShot] = []
    overlays: list[OverlaySpec] = []

    for skeleton_shot in skeleton.shots:
        exception = exceptions.get(skeleton_shot.shot_id)
        if exception:
            overlay = exception.overlay
            if overlay:
                overlays.append(overlay)
            shots.append(
                EditorialShot(
                    shot_id=skeleton_shot.shot_id,
                    chapter_id=skeleton_shot.chapter_id,
                    narration_ids=skeleton_shot.narration_ids,
                    claim_ids=skeleton_shot.claim_ids,
                    start=skeleton_shot.start,
                    end=skeleton_shot.end,
                    duration=skeleton_shot.duration,
                    narration_text=skeleton_shot.narration_text,
                    visual_purpose=skeleton_shot.visual_purpose,
                    story_function=skeleton_shot.story_function,
                    visual_mode=exception.mode,
                    master_asset_id=None,
                    overlay=overlay,
                    archive_source=exception.archive_source,
                    support_reason=exception.reason,
                )
            )
            continue

        decision = decisions.get(skeleton_shot.shot_id)
        if decision is None:
            raise EditorialPlanValidationError(
                f"{skeleton_shot.shot_id} has no final LLM assignment."
            )
        asset = assets[decision.asset_id]
        overlay = None
        if decision.overlay_type:
            overlay = OverlaySpec(
                type=decision.overlay_type,
                template_id=(
                    decision.overlay_template_id
                    or f"{decision.overlay_type}_v1"
                ),
                claim_ids=list(skeleton_shot.claim_ids),
                disclosure=asset.reconstruction_disclosure,
            )
            overlays.append(overlay)
        visual_mode = decision.visual_mode
        if overlay and visual_mode == "master_video":
            visual_mode = "master_video_with_overlay"
        if decision.reuse_operation == "freeze":
            visual_mode = "master_video_freeze"
        shots.append(
            EditorialShot(
                shot_id=skeleton_shot.shot_id,
                chapter_id=skeleton_shot.chapter_id,
                narration_ids=skeleton_shot.narration_ids,
                claim_ids=skeleton_shot.claim_ids,
                start=skeleton_shot.start,
                end=skeleton_shot.end,
                duration=skeleton_shot.duration,
                narration_text=skeleton_shot.narration_text,
                visual_purpose=skeleton_shot.visual_purpose,
                story_function=skeleton_shot.story_function,
                visual_mode=visual_mode,
                master_asset_id=decision.asset_id,
                reuse_operation=decision.reuse_operation,
                crop_id=decision.crop_id,
                playback_speed=decision.playback_speed,
                source_in=decision.source_in,
                source_out=(
                    decision.source_out or asset.source_duration_seconds
                ),
                overlay=overlay,
                support_reason=decision.support_reason,
                transition="hard_cut",
            )
        )

    return EditorialShotPlan(
        project_id=skeleton.project_id,
        shots=shots,
        total_seconds=skeleton.total_seconds,
        voiceover_sha256=skeleton.voiceover_sha256,
        master_plan_version=master_plan.plan_version,
        overlay_tracks=overlays,
    )


def validate_llm_assignment_plan(
    plan: EditorialShotPlan,
    skeleton: ShotSkeletonPlan,
    master_plan: MasterAssetPlan,
    eligibility_plan: AssignmentEligibilityPlan,
) -> None:
    """Use the established validator without mutating the approved plan on disk."""
    eligible_by_shot = {
        item.shot_id: {asset.asset_id for asset in item.eligible_assets}
        for item in eligibility_plan.shots
    }
    expanded = master_plan.model_copy(deep=True)
    expanded_assets = {item.asset_id: item for item in expanded.assets}
    for shot in plan.shots:
        if not shot.master_asset_id:
            continue
        if shot.master_asset_id not in eligible_by_shot.get(shot.shot_id, set()):
            raise EditorialPlanValidationError(
                f"{shot.shot_id} selected a package outside its objective "
                "eligibility set."
            )
        asset = expanded_assets[shot.master_asset_id]
        if shot.shot_id not in asset.linked_shots:
            asset.linked_shots.append(shot.shot_id)
    validate_editorial_plan(plan, skeleton, expanded)


def _write_legacy_mirror(project: Path, plan: EditorialShotPlan) -> None:
    legacy = ShotPlan(
        project_id=plan.project_id,
        total_seconds=plan.total_seconds,
        voiceover_sha256=plan.voiceover_sha256,
        shots=[
            Shot(
                shot_id=item.shot_id,
                chapter_id=item.chapter_id,
                narration_ids=item.narration_ids,
                claim_ids=item.claim_ids,
                start=item.start,
                end=item.end,
                duration=item.duration,
                narration_text=item.narration_text,
                visual_purpose=item.visual_purpose,
                story_function=item.story_function,
                factual_scope=item.claim_ids,
                visual_type=item.visual_mode,
                suggested_visual=item.support_reason,
                transition=item.transition,
                overlay_requirements=(
                    [item.overlay.type] if item.overlay else []
                ),
                requires_new_master_asset=False,
                candidate_master_asset=item.master_asset_id,
            )
            for item in plan.shots
        ],
    )
    write_json(project / "06_shots/shot_plan.json", legacy)
    write_json(project / "04_shot_plan/shot_plan.json", legacy)


def direct_editorial_shots_llm_all(
    store: ProjectStore,
    project_id: str,
    *,
    agent_kind: str = "routed",
    consume_response: bool = False,
) -> EditorialShotPlan:
    """Route every production creative package assignment through an LLM."""
    project = store.project_dir(project_id)
    skeleton = load_model(
        project / "06_shots/shot_skeleton.json",
        ShotSkeletonPlan,
    )
    compact_path = project / "06_shots/compact_shot_index.json"
    compact = (
        load_model(compact_path, CompactShotIndex)
        if compact_path.exists()
        else build_compact_shot_index(skeleton)
    )
    master_plan = approved_master_plan(project)
    exceptions = {
        item.shot_id for item in master_plan.non_generated_coverage
    }
    eligibility = build_hard_eligibility(
        compact,
        master_plan,
        excluded_shot_ids=exceptions,
    )
    write_json(
        project / "06_shots/assignment_eligibility.json",
        eligibility,
    )
    store.transition(project_id, ProjectState.SHOTS_GENERATING)

    if agent_kind in {"deterministic", "mock"}:
        decisions = _test_only_decisions(
            compact,
            eligibility,
            master_plan,
        )
        stats = {
            "assignment_shot_count": len(decisions),
            "batch_count": 0,
            "model_calls": 0,
            "cache_hits": 0,
        }
        assignment_mode = "deterministic_test_only"
    else:
        decisions, stats = assign_every_shot_with_llm(
            project=project,
            project_id=project_id,
            title=store.brief(project_id).title,
            compact=compact,
            master_plan=master_plan,
            eligibility_plan=eligibility,
            agent_kind=agent_kind,
            consume_response=consume_response,
        )
        assignment_mode = "llm_every_generated_media_shot"

    plan = _build_plan(
        skeleton=skeleton,
        master_plan=master_plan,
        decisions=decisions,
    )
    validate_llm_assignment_plan(
        plan,
        skeleton,
        master_plan,
        eligibility,
    )
    version = store.next_version(project_id, "editorial_shots")
    write_json(
        versioned_path(
            project / "06_shots",
            "editorial_shot_plan",
            ".json",
            version,
        ),
        plan,
    )
    write_json(project / "06_shots/editorial_shot_plan.json", plan)
    write_json(
        project / "06_shots/assignment_summary.json",
        {
            "assignment_mode": assignment_mode,
            "shot_count": len(skeleton.shots),
            "llm_assignment_count": (
                stats["assignment_shot_count"]
                if assignment_mode == "llm_every_generated_media_shot"
                else 0
            ),
            "local_creative_assignment_count": 0,
            "test_only_deterministic_assignment_count": (
                stats["assignment_shot_count"]
                if assignment_mode == "deterministic_test_only"
                else 0
            ),
            "preapproved_non_generated_count": len(exceptions),
            "assignment_batch_count": stats["batch_count"],
            "model_calls": stats["model_calls"],
            "cache_hits": stats["cache_hits"],
            "local_scoring_used": False,
            "model_reproduced_full_timeline": False,
        },
    )
    _write_legacy_mirror(project, plan)
    store.transition(project_id, ProjectState.SHOTS_REVIEW)
    return plan
