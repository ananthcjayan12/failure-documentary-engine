from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from fde.editorial import deterministic_editorial_plan, validate_editorial_plan
from fde.invalidation import invalidate_master_asset, invalidate_overlay
from fde.io import write_json
from fde.master_footage import (
    MasterPlanValidationError,
    deterministic_master_plan,
    validate_master_plan,
)
from fde.models import (
    EditorialShotPlan,
    MasterFootageStrategy,
    OverlaySpec,
    ProjectBrief,
    ShotSkeleton,
    ShotSkeletonPlan,
    V1MediaJob,
    V1MediaManifest,
)
from fde.project import ProjectStore


def skeleton(count: int = 30) -> ShotSkeletonPlan:
    shots = []
    for index in range(count):
        start = index * 5.0
        story_function = (
            "physical_story_moment" if index % 3 == 0
            else "evidence_explanation" if index % 3 == 1
            else "narrative_progression"
        )
        shots.append(
            ShotSkeleton(
                shot_id=f"SHOT_{index + 1:03d}",
                chapter_id=f"CH{index // 6 + 1:02d}",
                narration_ids=[f"paragraph_{index + 1:02d}"],
                claim_ids=[f"claim_{index + 1:02d}"],
                start=start,
                end=start + 5,
                duration=5,
                narration_text=f"Narration beat {index + 1}",
                visual_purpose=f"Explain evidence beat {index + 1}",
                story_function=story_function,
                factual_scope=[f"claim_{index + 1:02d}"],
            )
        )
    return ShotSkeletonPlan(
        project_id="two-pass",
        shots=shots,
        total_seconds=count * 5,
        voiceover_sha256="voice-sha",
    )


def brief() -> ProjectBrief:
    return ProjectBrief(
        project_id="two-pass",
        title="Two Pass",
        topic="Test",
        target_duration_seconds=150,
        maximum_master_assets=24,
        master_footage_strategy=MasterFootageStrategy(),
    )


def test_master_plan_enforces_exact_8_8_8_and_complete_coverage():
    shot_skeleton = skeleton()
    plan = deterministic_master_plan(brief(), shot_skeleton)
    validate_master_plan(plan, shot_skeleton, brief())
    assert len(plan.assets) == 24
    assert Counter(item.category for item in plan.assets) == {
        "hero": 8,
        "atmosphere": 8,
        "investigation": 8,
    }
    assert [item.asset_id for item in plan.assets] == [
        *[f"H{i:02d}" for i in range(1, 9)],
        *[f"L{i:02d}" for i in range(1, 9)],
        *[f"E{i:02d}" for i in range(1, 9)],
    ]
    assert all(item.linked_shots for item in plan.assets)
    assert all(item.loopable and item.seamless_loop_required for item in plan.assets[8:16])
    covered = {shot_id for item in plan.assets for shot_id in item.linked_shots}
    assert covered == {item.shot_id for item in shot_skeleton.shots}


def test_master_plan_validation_returns_actionable_errors():
    shot_skeleton = skeleton()
    plan = deterministic_master_plan(brief(), shot_skeleton)
    plan.assets[8].loopable = False
    plan.assets.pop()
    with pytest.raises(MasterPlanValidationError) as caught:
        validate_master_plan(plan, shot_skeleton, brief())
    message = str(caught.value)
    assert "Expected exactly 24 generated master assets" in message
    assert "Expected 8 investigation assets" in message
    assert "classified as atmosphere but is not configured as loopable" in message


def test_editorial_plan_preserves_audio_timing_and_uses_only_approved_assets():
    shot_skeleton = skeleton()
    plan = deterministic_master_plan(brief(), shot_skeleton)
    plan.plan_version = 2
    plan.status = "approved"
    editorial = deterministic_editorial_plan(shot_skeleton, plan)
    validate_editorial_plan(editorial, shot_skeleton, plan)
    assert editorial.master_plan_version == 2
    assert [(item.start, item.end) for item in editorial.shots] == [
        (item.start, item.end) for item in shot_skeleton.shots
    ]
    approved_ids = {item.asset_id for item in plan.assets}
    assert {item.master_asset_id for item in editorial.shots}.issubset(approved_ids)
    for item in editorial.shots:
        package = next(asset for asset in plan.assets if asset.asset_id == item.master_asset_id)
        assert item.shot_id in package.linked_shots
        assert item.source_out <= package.source_duration_seconds


def test_targeted_asset_and_overlay_invalidation_leave_other_jobs_current(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    project = store.create(
        ProjectBrief(project_id="targeted", title="Targeted", topic="Test")
    )
    write_json(
        project / "06_shots/editorial_shot_plan.json",
        EditorialShotPlan(
            project_id="targeted",
            total_seconds=10,
            voiceover_sha256="voice",
            master_plan_version=1,
            shots=[
                {
                    "shot_id": "SHOT_001", "start": 0, "end": 5, "duration": 5,
                    "master_asset_id": "H01", "support_reason": "approved package",
                },
                {
                    "shot_id": "SHOT_002", "start": 5, "end": 10, "duration": 5,
                    "master_asset_id": "L01", "support_reason": "approved package",
                },
            ],
        ),
    )
    for media_type, path in (
        ("image", project / "07_images/jobs.json"),
        ("video", project / "09_videos/jobs.json"),
    ):
        write_json(
            path,
            V1MediaManifest(
                project_id="targeted",
                media_type=media_type,
                jobs=[
                    V1MediaJob(
                        job_id=f"{media_type}-H01", asset_id="H01", media_type=media_type,
                        status="approved", prompt="one",
                    ),
                    V1MediaJob(
                        job_id=f"{media_type}-L01", asset_id="L01", media_type=media_type,
                        status="approved", prompt="two",
                    ),
                ],
            ),
        )
    targets = invalidate_master_asset(store, "targeted", "H01")
    assert "timeline:SHOT_001" in targets
    assert "timeline:SHOT_002" not in targets
    images = __import__("fde.io", fromlist=["load_model"]).load_model(
        project / "07_images/jobs.json", V1MediaManifest
    )
    assert images.jobs[0].status == "pending"
    assert images.jobs[1].status == "approved"

    write_json(
        project / "12_timeline/timeline.json",
        {
            "project_id": "targeted",
            "total_seconds": 10,
            "overlay_tracks": {"OVL_001": OverlaySpec(type="radar_track", template_id="radar_v1")},
            "entries": [
                {
                    "timeline_id": "TL_001", "shot_id": "SHOT_001",
                    "timeline_start": 0, "timeline_end": 5, "narration_ids": [],
                    "media_kind": "coded_graphic", "overlay_track_ids": ["OVL_001"],
                },
                {
                    "timeline_id": "TL_002", "shot_id": "SHOT_002",
                    "timeline_start": 5, "timeline_end": 10, "narration_ids": [],
                    "media_kind": "placeholder", "overlay_track_ids": [],
                },
            ],
        },
    )
    overlay_targets = invalidate_overlay(store, "targeted", "OVL_001")
    assert "timeline:SHOT_001" in overlay_targets
    assert "timeline:SHOT_002" not in overlay_targets
