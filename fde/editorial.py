from __future__ import annotations

from pathlib import Path

from .agents import get_agent
from .io import load_model, versioned_path, write_json
from .master_footage import approved_master_plan
from .models import (
    DocumentaryScript,
    EditorialShot,
    EditorialShotPlan,
    MasterAssetPlan,
    OverlaySpec,
    ProjectState,
    ResearchDossier,
    Shot,
    ShotPlan,
    ShotSkeleton,
    ShotSkeletonPlan,
)
from .project import ProjectStore
from .prompts import render_prompt


class EditorialPlanValidationError(ValueError):
    pass


MASTER_MODES = {
    "master_video",
    "master_video_with_overlay",
    "master_video_freeze",
    "generated_still",
}
NON_GENERATED_MODES = {
    "coded_graphic",
    "archive_media",
    "black_or_negative_space",
}


def _load_script(project: Path) -> DocumentaryScript:
    path = project / "03_narration/narration.json"
    if not path.exists():
        path = project / "03_script/script.json"
    return load_model(path, DocumentaryScript)


def _copy_immutable(skeleton: ShotSkeleton, proposal: EditorialShot) -> EditorialShot:
    result = proposal.model_copy(deep=True)
    result.shot_id = skeleton.shot_id
    result.chapter_id = skeleton.chapter_id
    result.narration_ids = list(skeleton.narration_ids)
    result.claim_ids = list(skeleton.claim_ids)
    result.start = skeleton.start
    result.end = skeleton.end
    result.duration = skeleton.duration
    result.narration_text = skeleton.narration_text
    result.visual_purpose = skeleton.visual_purpose
    result.story_function = skeleton.story_function
    return result


def validate_editorial_plan(
    plan: EditorialShotPlan,
    skeleton: ShotSkeletonPlan,
    master_plan: MasterAssetPlan,
) -> None:
    errors: list[str] = []
    if plan.project_id != skeleton.project_id:
        errors.append("Editorial plan changed project_id.")
    if plan.voiceover_sha256 != skeleton.voiceover_sha256:
        errors.append("Editorial plan changed the approved voiceover hash.")
    if abs(plan.total_seconds - skeleton.total_seconds) > 0.01:
        errors.append("Editorial plan changed the total audio-led duration.")
    if plan.master_plan_version != master_plan.plan_version:
        errors.append(
            f"Editorial plan references master-plan version {plan.master_plan_version}; "
            f"approved version is {master_plan.plan_version}."
        )
    expected_ids = [item.shot_id for item in skeleton.shots]
    actual_ids = [item.shot_id for item in plan.shots]
    if actual_ids != expected_ids:
        errors.append("Editorial plan must return every immutable shot ID in the original order.")
    skeleton_by_id = {item.shot_id: item for item in skeleton.shots}
    assets = {item.asset_id: item for item in master_plan.assets}
    coverage = {item.shot_id: item for item in master_plan.non_generated_coverage}
    for shot in plan.shots:
        original = skeleton_by_id.get(shot.shot_id)
        if original is None:
            continue
        for field in ("start", "end", "duration"):
            if abs(float(getattr(shot, field)) - float(getattr(original, field))) > 0.01:
                errors.append(f"{shot.shot_id} changed immutable {field}.")
        if shot.narration_ids != original.narration_ids:
            errors.append(f"{shot.shot_id} changed immutable narration_ids.")
        if shot.claim_ids != original.claim_ids:
            errors.append(f"{shot.shot_id} changed immutable claim_ids.")
        if shot.visual_mode in MASTER_MODES:
            if not shot.master_asset_id:
                errors.append(f"{shot.shot_id} requires master_asset_id.")
                continue
            asset = assets.get(shot.master_asset_id)
            if asset is None:
                errors.append(
                    f"{shot.shot_id} references unapproved master asset {shot.master_asset_id}."
                )
                continue
            if shot.shot_id not in asset.linked_shots:
                errors.append(
                    f"{shot.shot_id} is not approved for reuse of {shot.master_asset_id}."
                )
            operation = "loop" if shot.reuse_operation == "loop_and_slow" else shot.reuse_operation
            if operation not in asset.allowed_operations:
                errors.append(
                    f"{shot.shot_id} uses {shot.reuse_operation}, which is not allowed by "
                    f"{asset.asset_id}."
                )
            if shot.crop_id and shot.crop_id not in {item.crop_id for item in asset.crop_regions}:
                errors.append(
                    f"{shot.shot_id} uses unknown crop {shot.crop_id} on {asset.asset_id}."
                )
            if not (asset.playback_speed_min <= shot.playback_speed <= asset.playback_speed_max):
                errors.append(
                    f"{shot.shot_id} playback speed {shot.playback_speed} is outside "
                    f"{asset.asset_id}'s {asset.playback_speed_min}–{asset.playback_speed_max} range."
                )
            source_out = shot.source_out or asset.source_duration_seconds
            if source_out > asset.source_duration_seconds + 0.01:
                errors.append(
                    f"{shot.shot_id} source_out exceeds {asset.asset_id}'s "
                    f"{asset.source_duration_seconds:g}-second source."
                )
            if shot.source_in >= source_out:
                errors.append(f"{shot.shot_id} source_in must be before source_out.")
            if shot.visual_mode == "master_video_with_overlay" and shot.overlay is None:
                errors.append(f"{shot.shot_id} requests an overlay but has no typed OverlaySpec.")
            if shot.reuse_operation == "reverse_loop" and asset.category != "atmosphere":
                errors.append(
                    f"{shot.shot_id} reverse_loop is unsafe for non-atmosphere asset {asset.asset_id}."
                )
        elif shot.visual_mode in NON_GENERATED_MODES:
            assignment = coverage.get(shot.shot_id)
            if assignment is None:
                errors.append(
                    f"{shot.shot_id} uses {shot.visual_mode} without approved non-generated coverage."
                )
            elif assignment.mode != shot.visual_mode:
                errors.append(
                    f"{shot.shot_id} visual mode {shot.visual_mode} does not match approved "
                    f"coverage mode {assignment.mode}."
                )
            if shot.master_asset_id:
                errors.append(
                    f"{shot.shot_id} is a non-generated visual and must not consume a master asset."
                )
            if shot.visual_mode == "coded_graphic" and shot.overlay is None:
                errors.append(f"{shot.shot_id} coded graphic requires a typed OverlaySpec.")
            if shot.visual_mode == "archive_media" and not shot.archive_source:
                errors.append(f"{shot.shot_id} archive media requires an approved source path.")
        else:
            errors.append(f"{shot.shot_id} has unsupported visual_mode {shot.visual_mode}.")
        if not shot.support_reason.strip():
            errors.append(f"{shot.shot_id} must explain why the visual supports the narration.")
    if errors:
        raise EditorialPlanValidationError("\n".join(errors))


def deterministic_editorial_plan(
    skeleton: ShotSkeletonPlan,
    master_plan: MasterAssetPlan,
) -> EditorialShotPlan:
    assets_by_shot: dict[str, list] = {}
    for asset in master_plan.assets:
        for shot_id in asset.linked_shots:
            assets_by_shot.setdefault(shot_id, []).append(asset)
    exceptions = {item.shot_id: item for item in master_plan.non_generated_coverage}
    shots: list[EditorialShot] = []
    overlays: list[OverlaySpec] = []
    usage_count: dict[str, int] = {}
    for item in skeleton.shots:
        exception = exceptions.get(item.shot_id)
        if exception:
            overlay = exception.overlay
            if overlay:
                overlays.append(overlay)
            shots.append(
                EditorialShot(
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
                    visual_mode=exception.mode,
                    master_asset_id=None,
                    reuse_operation="full_frame",
                    playback_speed=1.0,
                    source_in=0,
                    source_out=item.duration,
                    overlay=overlay,
                    archive_source=exception.archive_source,
                    support_reason=exception.reason,
                    transition="hard_cut",
                )
            )
            continue
        candidates = assets_by_shot.get(item.shot_id, [])
        if not candidates:
            raise EditorialPlanValidationError(f"{item.shot_id} has no approved visual coverage.")
        # Prefer the least-used approved package to keep callbacks intentional.
        asset = min(candidates, key=lambda value: usage_count.get(value.asset_id, 0))
        usage_count[asset.asset_id] = usage_count.get(asset.asset_id, 0) + 1
        if item.duration > asset.source_duration_seconds and asset.loopable:
            operation = "loop_and_slow" if asset.playback_speed_min <= 0.8 else "loop"
            speed = max(asset.playback_speed_min, 0.8)
        elif item.duration > asset.source_duration_seconds:
            operation = "freeze"
            speed = 1.0
        elif usage_count[asset.asset_id] > 1:
            operation = "callback"
            speed = 1.0
        else:
            operation = "full_frame"
            speed = 1.0
        crop_id = asset.crop_regions[
            (usage_count[asset.asset_id] - 1) % len(asset.crop_regions)
        ].crop_id if asset.crop_regions else None
        shots.append(
            EditorialShot(
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
                visual_mode="master_video_freeze" if operation == "freeze" else "master_video",
                master_asset_id=asset.asset_id,
                reuse_operation=operation,
                crop_id=crop_id,
                playback_speed=speed,
                source_in=0,
                source_out=asset.source_duration_seconds,
                support_reason=(
                    f"{asset.asset_id} is approved for this shot and its factual scope, "
                    "crop regions, and reuse operations support the spoken beat."
                ),
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


def _apply_director_response(
    skeleton: ShotSkeletonPlan,
    proposal: EditorialShotPlan,
    master_plan: MasterAssetPlan,
) -> EditorialShotPlan:
    proposal_by_id = {item.shot_id: item for item in proposal.shots}
    if list(proposal_by_id) != [item.shot_id for item in skeleton.shots]:
        raise EditorialPlanValidationError(
            "Visual director must return every immutable shot ID in original order."
        )
    final = EditorialShotPlan(
        project_id=skeleton.project_id,
        shots=[
            _copy_immutable(item, proposal_by_id[item.shot_id])
            for item in skeleton.shots
        ],
        total_seconds=skeleton.total_seconds,
        voiceover_sha256=skeleton.voiceover_sha256,
        master_plan_version=master_plan.plan_version,
        overlay_tracks=proposal.overlay_tracks,
    )
    validate_editorial_plan(final, skeleton, master_plan)
    return final


def direct_editorial_shots(
    store: ProjectStore,
    project_id: str,
    *,
    agent_kind: str = "routed",
    consume_response: bool = False,
) -> EditorialShotPlan:
    project = store.project_dir(project_id)
    skeleton = load_model(project / "06_shots/shot_skeleton.json", ShotSkeletonPlan)
    master_plan = approved_master_plan(project)
    store.transition(project_id, ProjectState.SHOTS_GENERATING)
    if agent_kind in {"deterministic", "mock"}:
        plan = deterministic_editorial_plan(skeleton, master_plan)
    else:
        research = load_model(project / "01_research/source_dossier.json", ResearchDossier)
        script = _load_script(project)
        context = {
            "project_id": project_id,
            "title": script.title,
            "duration": skeleton.total_seconds,
            "research": research,
            "script": script,
            "shot_skeleton": skeleton,
            "master_footage_plan": master_plan,
        }
        agent = get_agent(agent_kind, context, consume_response)
        proposal = agent.run(
            stage="editorial_shots",
            prompt=render_prompt(
                "editorial_shots",
                research=research,
                script=script,
                shot_skeleton=skeleton,
                master_plan=master_plan,
            ),
            output_model=EditorialShotPlan,
            request_dir=project / "_requests",
        )
        plan = _apply_director_response(skeleton, proposal, master_plan)
        write_json(project / "06_shots/editorial_director_response.json", proposal)
    validate_editorial_plan(plan, skeleton, master_plan)
    version = store.next_version(project_id, "editorial_shots")
    write_json(
        versioned_path(project / "06_shots", "editorial_shot_plan", ".json", version),
        plan,
    )
    write_json(project / "06_shots/editorial_shot_plan.json", plan)

    # Compatibility mirror contains assignments only; no independent generation prompts.
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
                image_prompt="",
                video_prompt="",
                transition=item.transition,
                overlay_requirements=[item.overlay.type] if item.overlay else [],
                requires_new_master_asset=False,
                candidate_master_asset=item.master_asset_id,
            )
            for item in plan.shots
        ],
    )
    write_json(project / "06_shots/shot_plan.json", legacy)
    write_json(project / "04_shot_plan/shot_plan.json", legacy)
    store.transition(project_id, ProjectState.SHOTS_REVIEW)
    return plan


def approve_editorial_shots(store: ProjectStore, project_id: str) -> EditorialShotPlan:
    project = store.project_dir(project_id)
    skeleton = load_model(project / "06_shots/shot_skeleton.json", ShotSkeletonPlan)
    master_plan = approved_master_plan(project)
    plan = load_model(project / "06_shots/editorial_shot_plan.json", EditorialShotPlan)
    validate_editorial_plan(plan, skeleton, master_plan)
    version = store.manifest(project_id).current_versions.get("editorial_shots")
    if not version:
        raise RuntimeError("no current editorial-shot version")
    store.approve_version(project_id, "editorial_shots", version)
    write_json(
        project / "06_shots" / f"editorial_shot_plan_v{version:02d}_approved.json",
        plan,
    )
    store.transition(project_id, ProjectState.SHOTS_APPROVED)
    return plan
