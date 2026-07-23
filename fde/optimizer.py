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


def _legacy_strategy(maximum_assets: int) -> MasterFootageStrategy:
    count = max(1, maximum_assets)
    hero = max(1, count // 3) if count >= 3 else 1
    remaining = count - hero
    atmosphere = max(0, remaining // 2)
    investigation = max(0, remaining - atmosphere)
    if count == 1:
        atmosphere = investigation = 0
    return MasterFootageStrategy(
        hero_count=hero,
        atmosphere_count=atmosphere,
        investigation_count=investigation,
        target_generated_video_count=count,
        enforce_exact_counts=True,
    )


def optimize_shots(shot_plan: ShotPlan, maximum_assets: int) -> MasterAssetPlan:
    """Compatibility wrapper for callers of the removed semantic-clustering API.

    Production uses `plan_master_footage()` with the explicit 8 / 8 / 8 strategy.
    Older tests and projects may still request a smaller safety limit; they receive a
    deterministic legacy proposal rather than semantic text-similarity clustering.
    """
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
    strategy = MasterFootageStrategy() if maximum_assets >= 24 else _legacy_strategy(maximum_assets)
    brief = ProjectBrief(
        project_id=shot_plan.project_id,
        title=shot_plan.project_id,
        topic=shot_plan.project_id,
        maximum_master_assets=maximum_assets,
        master_footage_strategy=strategy,
    )
    plan = deterministic_master_plan(brief, skeleton)
    plan.status = "legacy"
    return plan
