from fde.editorial import (
    _master_plan_for_editorial_prompt,
    canonical_asset_operations,
    editorial_master_contract,
    validate_editorial_plan,
)
from fde.models import (
    CropRegion,
    EditorialShot,
    EditorialShotPlan,
    MasterAsset,
    MasterAssetPlan,
    ShotSkeleton,
    ShotSkeletonPlan,
)


def _master_plan() -> MasterAssetPlan:
    return MasterAssetPlan(
        project_id="contract",
        maximum_assets=1,
        plan_version=2,
        status="approved",
        assets=[
            MasterAsset(
                asset_id="H07",
                title="Hero reconstruction",
                category="hero",
                linked_shots=["SHOT_001"],
                primary_use="Approved reconstruction",
                allowed_operations=[
                    "hero_render",
                    "slow_motion",
                    "overlay_diagram",
                ],
                crop_regions=[
                    CropRegion(crop_id="crop_01", description="Approved crop")
                ],
                source_duration_seconds=6,
            )
        ],
    )


def _skeleton() -> ShotSkeletonPlan:
    return ShotSkeletonPlan(
        project_id="contract",
        voiceover_sha256="voice",
        total_seconds=6,
        shots=[
            ShotSkeleton(
                shot_id="SHOT_001",
                start=0,
                end=6,
                duration=6,
            )
        ],
    )


def test_legacy_master_operation_labels_become_closed_editorial_tokens():
    assert canonical_asset_operations(
        ["hero_render", "slow_motion", "overlay_diagram", "unknown"]
    ) == ["full_frame", "slow", "overlay_background"]

    plan = _master_plan()
    prompt_plan = _master_plan_for_editorial_prompt(plan)
    contract = editorial_master_contract(plan)

    assert plan.assets[0].allowed_operations == [
        "hero_render",
        "slow_motion",
        "overlay_diagram",
    ]
    assert prompt_plan.assets[0].allowed_operations == [
        "full_frame",
        "slow",
        "overlay_background",
    ]
    assert contract[0]["allowed_reuse_operations"] == [
        "full_frame",
        "slow",
        "overlay_background",
    ]


def test_slow_is_valid_when_approved_master_capability_is_slow_motion():
    plan = _master_plan()
    skeleton = _skeleton()
    editorial = EditorialShotPlan(
        project_id="contract",
        voiceover_sha256="voice",
        total_seconds=6,
        master_plan_version=2,
        shots=[
            EditorialShot(
                shot_id="SHOT_001",
                start=0,
                end=6,
                duration=6,
                master_asset_id="H07",
                reuse_operation="slow",
                crop_id="crop_01",
                playback_speed=0.8,
                source_out=6,
                support_reason="Slow playback supports the narration.",
            )
        ],
    )

    validate_editorial_plan(editorial, skeleton, plan)
