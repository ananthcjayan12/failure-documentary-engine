from __future__ import annotations

from .master_footage import deterministic_master_plan
from .models import (
    MasterAssetPlan,
    MasterFootageStrategy,
    ProjectBrief,
    ShotPlan,
    ShotSkeleton,
    ShotSkeletonPlan,
)


def optimize_shots(shot_plan: ShotPlan, maximum_assets: int) -> MasterAssetPlan:
    """Compatibility wrapper for callers of the old semantic-clustering API.

    The production pipeline no longer groups independent shot prompts by text similarity.
    It constructs an explicit reusable footage vocabulary first. New code should call
    `plan_master_footage()`; this wrapper converts an old audio-led ShotPlan into the
    deterministic two-pass contract without overwriting any project artifact.
    """
    if maximum_assets < 24:
        raise ValueError(
            "The default two-pass strategy requires maximum_assets >= 24 "
            "for 8 hero, 8 atmosphere, and 8 investigation packages."
        )
    skeleton = ShotSkeletonPlan(
        project_id=shot_plan.project_id,
        total_seconds=shot_plan.total_seconds,
        voiceover_sha256=shot_plan.voiceover_sha256,
        timing_source="legacy_shot_plan_compatibility",
        shots=[
            ShotSkeleton(
                shot_id=item.shot_id,
                chapter_id=item.chapter_id,
                narration_ids=item.narration_ids,
                claim_ids=item.claim_ids,
                start=item.start,
                end=item.end or item.start + item.duration,
                duration=item.duration,
                narration_text=item.narration_text,
                visual_purpose=item.visual_purpose,
                story_function=item.story_function or item.suspense_function,
                factual_scope=item.factual_scope or item.claim_ids,
            )
            for item in shot_plan.shots
        ],
    )
    brief = ProjectBrief(
        project_id=shot_plan.project_id,
        title=shot_plan.project_id,
        topic=shot_plan.project_id,
        maximum_master_assets=maximum_assets,
        master_footage_strategy=MasterFootageStrategy(),
    )
    return deterministic_master_plan(brief, skeleton)
