from __future__ import annotations

from collections import Counter

from .models import (
    CropRegion,
    DisclosureLabel,
    MasterAsset,
    MasterAssetPlan,
    MasterFootageStrategy,
    ShotPlan,
)


CATEGORY_ORDER = ("hero", "atmosphere", "investigation")
CATEGORY_PREFIX = {"hero": "H", "atmosphere": "L", "investigation": "E"}


def optimize_shots(shot_plan: ShotPlan, maximum_assets: int) -> MasterAssetPlan:
    """Compatibility replacement for the removed text-similarity optimizer.

    Production uses the reviewed `plan_master_footage()` flow. This function exists
    only for older callers: it deterministically partitions every legacy shot exactly
    once across at most `maximum_assets`, preserving the previous hard-limit and
    coverage contract without reintroducing semantic clustering.
    """
    if maximum_assets < 1:
        raise ValueError("maximum_assets must be at least one")
    if not shot_plan.shots:
        return MasterAssetPlan(
            project_id=shot_plan.project_id,
            maximum_assets=maximum_assets,
            strategy=MasterFootageStrategy(
                hero_count=1,
                atmosphere_count=0,
                investigation_count=0,
                target_generated_video_count=1,
            ),
            status="legacy",
            assets=[],
            uncovered_shots=[],
        )
    asset_count = min(maximum_assets, len(shot_plan.shots))
    groups: list[list] = [[] for _ in range(asset_count)]
    for index, shot in enumerate(shot_plan.shots):
        groups[index % asset_count].append(shot)

    counts: Counter[str] = Counter()
    assets: list[MasterAsset] = []
    for group_index, linked in enumerate(groups):
        first = linked[0]
        category = CATEGORY_ORDER[group_index % len(CATEGORY_ORDER)]
        counts[category] += 1
        asset_id = f"{CATEGORY_PREFIX[category]}{counts[category]:02d}"
        claim_ids = list(dict.fromkeys(claim for shot in linked for claim in shot.claim_ids))
        crop_regions = [
            CropRegion(crop_id="wide", description="Full reusable landscape frame"),
            CropRegion(crop_id="detail", description="Stable secondary detail crop"),
        ]
        assets.append(
            MasterAsset(
                asset_id=asset_id,
                title=first.suggested_visual or first.visual_purpose or asset_id,
                category=category,
                linked_shots=[shot.shot_id for shot in linked],
                primary_use=first.visual_purpose or first.suggested_visual,
                secondary_uses=[
                    shot.visual_purpose
                    for shot in linked[1:]
                    if shot.visual_purpose and shot.visual_purpose != first.visual_purpose
                ],
                required_reuse_count=len(linked),
                factual_scope=claim_ids,
                factual_context_id=first.chapter_id or f"legacy_{group_index:02d}",
                source_duration_seconds=5,
                loopable=category == "atmosphere",
                seamless_loop_required=category == "atmosphere",
                camera_stationary=category == "atmosphere",
                maximum_continuous_use_seconds=25 if category == "atmosphere" else 15,
                allowed_operations=(
                    ["full_frame", "crop", "loop", "slow", "freeze", "overlay_background"]
                    if category == "atmosphere"
                    else ["full_frame", "crop", "slow", "freeze", "callback"]
                ),
                crop_regions=crop_regions,
                major_story_moment=category == "hero",
                reconstruction_disclosure=(
                    DisclosureLabel(required=True) if category == "investigation" else None
                ),
                reuse_rationale="Legacy deterministic partition preserving exact one-time shot coverage.",
            )
        )
    strategy = MasterFootageStrategy(
        hero_count=counts["hero"],
        atmosphere_count=counts["atmosphere"],
        investigation_count=counts["investigation"],
        target_generated_video_count=asset_count,
        enforce_exact_counts=True,
    )
    return MasterAssetPlan(
        project_id=shot_plan.project_id,
        maximum_assets=maximum_assets,
        strategy=strategy,
        status="legacy",
        assets=assets,
        uncovered_shots=[],
    )
