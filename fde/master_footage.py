from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from .agents import get_agent
from .io import load_model, read_json, versioned_path, write_json
from .models import (
    CoverageAssignment,
    CropRegion,
    DisclosureLabel,
    DocumentaryScript,
    MasterAsset,
    MasterAssetPlan,
    MasterFootageStrategy,
    ProjectBrief,
    ProjectState,
    ResearchDossier,
    Shot,
    ShotPlan,
    ShotSkeleton,
    ShotSkeletonPlan,
)
from .project import ProjectStore
from .prompts import render_prompt


class MasterPlanValidationError(ValueError):
    pass


CATEGORY_PREFIX = {
    "hero": "H",
    "atmosphere": "L",
    "investigation": "E",
}


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _default_crop_regions(category: str) -> list[CropRegion]:
    if category == "hero":
        return [
            CropRegion(crop_id="wide_event", description="Full cinematic event composition"),
            CropRegion(crop_id="subject_detail", description="Stable detail crop preserving subject identity"),
        ]
    if category == "atmosphere":
        return [
            CropRegion(crop_id="wide_environment", description="Full overlay-safe environmental frame"),
            CropRegion(crop_id="texture_detail", description="Secondary environmental texture region"),
        ]
    return [
        CropRegion(crop_id="wide_investigation", description="Full technical or investigative environment"),
        CropRegion(crop_id="evidence_detail", description="Controlled detail region without embedded factual text"),
    ]


def _category_defaults(asset: MasterAsset, strategy: MasterFootageStrategy) -> MasterAsset:
    asset.source_duration_seconds = strategy.source_video_duration_seconds
    asset.required_reuse_count = max(1, len(asset.linked_shots))
    asset.linked_shots = _dedupe(asset.linked_shots)
    asset.factual_scope = _dedupe(asset.factual_scope)
    asset.crop_regions = asset.crop_regions or _default_crop_regions(asset.category)
    asset.overlay_safe_zones = asset.overlay_safe_zones or ["upper_right", "center"]
    asset.prohibited_details = _dedupe([*asset.prohibited_details, "embedded text", "watermark"])
    if asset.category == "hero":
        asset.major_story_moment = True
        asset.loopable = False
        asset.allowed_operations = _dedupe(
            asset.allowed_operations or ["full_frame", "crop", "slow", "freeze", "callback", "match_cut"]
        )
        asset.maximum_continuous_use_seconds = max(asset.maximum_continuous_use_seconds, 10)
    elif asset.category == "atmosphere":
        asset.loopable = True
        asset.camera_stationary = True
        asset.seamless_loop_required = True
        asset.opening_frame_stable = True
        asset.ending_frame_stable = True
        asset.allowed_operations = _dedupe(
            [
                *(asset.allowed_operations or []),
                "full_frame",
                "loop",
                "slow",
                "freeze",
                "crop",
                "overlay_background",
                "callback",
            ]
        )
        asset.maximum_continuous_use_seconds = max(asset.maximum_continuous_use_seconds, 25)
    elif asset.category == "investigation":
        asset.allowed_operations = _dedupe(
            [
                *(asset.allowed_operations or []),
                "full_frame",
                "crop",
                "slow",
                "freeze",
                "overlay_background",
                "callback",
            ]
        )
        asset.supported_overlay_families = _dedupe(
            [
                *asset.supported_overlay_families,
                "map",
                "radar",
                "timeline",
                "transcript",
                "satellite_arc",
                "technical_diagram",
                "disclosure_label",
            ]
        )
        if asset.reconstruction_disclosure is None:
            asset.reconstruction_disclosure = DisclosureLabel(required=True)
        asset.maximum_continuous_use_seconds = max(asset.maximum_continuous_use_seconds, 15)
    return asset


def normalize_master_plan(
    plan: MasterAssetPlan,
    *,
    brief: ProjectBrief,
    skeleton: ShotSkeletonPlan,
    version: int,
) -> MasterAssetPlan:
    """Make IDs and project-controlled fields deterministic without inventing the creative plan."""
    plan.project_id = skeleton.project_id
    plan.maximum_assets = brief.maximum_master_assets
    plan.strategy = brief.master_footage_strategy.model_copy(deep=True)
    plan.plan_version = version
    plan.status = "proposal"
    grouped: dict[str, list[MasterAsset]] = defaultdict(list)
    for asset in plan.assets:
        grouped[asset.category].append(asset)
    ordered: list[MasterAsset] = []
    for category in ("hero", "atmosphere", "investigation"):
        for index, asset in enumerate(grouped.get(category, []), start=1):
            asset.asset_id = f"{CATEGORY_PREFIX[category]}{index:02d}"
            ordered.append(_category_defaults(asset, plan.strategy))
    # A new two-pass plan cannot quietly keep old story_specific packages.
    ordered.extend(grouped.get("story_specific", []))
    plan.assets = ordered
    plan.non_generated_coverage = list(
        {item.shot_id: item for item in plan.non_generated_coverage}.values()
    )
    valid_ids = {item.shot_id for item in skeleton.shots}
    covered = {
        shot_id
        for asset in plan.assets
        for shot_id in asset.linked_shots
        if shot_id in valid_ids
    } | {
        item.shot_id for item in plan.non_generated_coverage if item.shot_id in valid_ids
    }
    plan.uncovered_shots = [item.shot_id for item in skeleton.shots if item.shot_id not in covered]
    return plan


def validate_master_plan(
    plan: MasterAssetPlan,
    skeleton: ShotSkeletonPlan,
    brief: ProjectBrief,
) -> None:
    errors: list[str] = []
    strategy = brief.master_footage_strategy
    if brief.maximum_master_assets < strategy.target_generated_video_count:
        errors.append(
            f"maximum_master_assets is {brief.maximum_master_assets}, but the strategy requires "
            f"{strategy.target_generated_video_count} generated packages."
        )
    if len(plan.assets) > brief.maximum_master_assets:
        errors.append(
            f"Plan contains {len(plan.assets)} assets, exceeding maximum_master_assets="
            f"{brief.maximum_master_assets}."
        )
    if strategy.enforce_exact_counts and len(plan.assets) != strategy.target_generated_video_count:
        errors.append(
            f"Expected exactly {strategy.target_generated_video_count} generated master assets; "
            f"received {len(plan.assets)}."
        )
    counts = Counter(item.category for item in plan.assets)
    expected = {
        "hero": strategy.hero_count,
        "atmosphere": strategy.atmosphere_count,
        "investigation": strategy.investigation_count,
    }
    for category, count in expected.items():
        if counts.get(category, 0) != count:
            errors.append(
                f"Expected {count} {category} assets; received {counts.get(category, 0)}."
            )
    if counts.get("story_specific", 0):
        errors.append(
            "New master-footage proposals cannot contain story_specific generated assets; "
            "use hero, atmosphere, investigation, or non-generated coverage."
        )

    skeleton_by_id = {item.shot_id: item for item in skeleton.shots}
    expected_ids = [
        *[f"H{index:02d}" for index in range(1, strategy.hero_count + 1)],
        *[f"L{index:02d}" for index in range(1, strategy.atmosphere_count + 1)],
        *[f"E{index:02d}" for index in range(1, strategy.investigation_count + 1)],
    ]
    actual_ids = [item.asset_id for item in plan.assets]
    if actual_ids != expected_ids:
        errors.append(
            "Master asset IDs must be deterministic and ordered according to the configured "
            "hero, atmosphere, and investigation counts."
        )
    if len(actual_ids) != len(set(actual_ids)):
        errors.append("Master asset IDs must be unique.")

    covered: set[str] = set()
    for asset in plan.assets:
        if not asset.linked_shots:
            errors.append(f"{asset.asset_id} has no linked shots.")
            continue
        for shot_id in asset.linked_shots:
            if shot_id not in skeleton_by_id:
                errors.append(f"{asset.asset_id} links unknown shot {shot_id}.")
                continue
            covered.add(shot_id)
        linked_claims = _dedupe(
            claim
            for shot_id in asset.linked_shots
            if shot_id in skeleton_by_id
            for claim in skeleton_by_id[shot_id].claim_ids
        )
        missing_claims = [claim for claim in linked_claims if claim not in asset.factual_scope]
        if missing_claims:
            errors.append(
                f"{asset.asset_id} factual_scope omits linked claim(s): {', '.join(missing_claims)}."
            )
        if not asset.reuse_rationale.strip():
            errors.append(f"{asset.asset_id} must explain why reuse across linked shots is valid.")
        if asset.category == "atmosphere" and not asset.loopable:
            errors.append(
                f"{asset.asset_id} is classified as atmosphere but is not configured as loopable."
            )
        if asset.category == "atmosphere" and not asset.seamless_loop_required:
            errors.append(
                f"{asset.asset_id} atmosphere footage must require a seamless loop."
            )
        if asset.category == "hero" and not asset.major_story_moment:
            errors.append(
                f"{asset.asset_id} is a hero asset but is not marked as a major physical story moment."
            )
        if asset.category == "investigation":
            if not asset.factual_context_id.strip():
                errors.append(
                    f"{asset.asset_id} investigation footage must declare factual_context_id."
                )
            if not asset.factual_scope:
                errors.append(
                    f"{asset.asset_id} investigation footage must declare factual_scope."
                )
            if asset.reconstruction_disclosure is None:
                errors.append(
                    f"{asset.asset_id} investigation footage must declare reconstruction boundaries."
                )
        crop_ids = [item.crop_id for item in asset.crop_regions]
        if len(crop_ids) != len(set(crop_ids)):
            errors.append(f"{asset.asset_id} contains duplicate crop IDs.")
        if asset.playback_speed_min > asset.playback_speed_max:
            errors.append(f"{asset.asset_id} has an invalid playback-speed range.")

    coverage_by_shot: dict[str, CoverageAssignment] = {}
    for item in plan.non_generated_coverage:
        if item.shot_id not in skeleton_by_id:
            errors.append(f"Non-generated coverage references unknown shot {item.shot_id}.")
            continue
        if item.shot_id in coverage_by_shot:
            errors.append(f"{item.shot_id} has duplicate non-generated coverage assignments.")
        coverage_by_shot[item.shot_id] = item
        covered.add(item.shot_id)
        if item.mode == "coded_graphic" and item.overlay is None:
            errors.append(
                f"{item.shot_id} uses coded_graphic coverage but has no typed overlay specification."
            )
        if item.mode == "archive_media" and not item.archive_source:
            errors.append(
                f"{item.shot_id} uses archive_media coverage but has no approved archive source."
            )

    uncovered = [item.shot_id for item in skeleton.shots if item.shot_id not in covered]
    if uncovered:
        errors.extend(f"{shot_id} has no visual coverage." for shot_id in uncovered)
    if plan.continuity_conflicts:
        errors.extend(f"Continuity conflict: {item}" for item in plan.continuity_conflicts)
    if errors:
        raise MasterPlanValidationError("\n".join(errors))


def _assigned_category(shot: ShotSkeleton) -> str:
    if shot.story_function in {"cold_open", "physical_story_moment", "human_resolution"}:
        return "hero"
    if shot.story_function in {"evidence_explanation", "technical_explanation"}:
        return "investigation"
    return "atmosphere"


def deterministic_master_plan(
    brief: ProjectBrief,
    skeleton: ShotSkeletonPlan,
) -> MasterAssetPlan:
    if not skeleton.shots:
        raise ValueError("shot skeleton is empty")
    strategy = brief.master_footage_strategy
    assets: list[MasterAsset] = []
    category_assets: dict[str, list[MasterAsset]] = defaultdict(list)
    category_counts = {
        "hero": strategy.hero_count,
        "atmosphere": strategy.atmosphere_count,
        "investigation": strategy.investigation_count,
    }
    global_index = 0
    for category in ("hero", "atmosphere", "investigation"):
        for index in range(1, category_counts[category] + 1):
            shot = skeleton.shots[global_index % len(skeleton.shots)]
            global_index += 1
            claim_scope = shot.claim_ids or shot.factual_scope
            title_fragment = " ".join(shot.narration_text.split()[:8]).strip() or shot.shot_id
            asset = MasterAsset(
                asset_id=f"{CATEGORY_PREFIX[category]}{index:02d}",
                title=f"{category.title()} package — {title_fragment}",
                category=category,
                linked_shots=[shot.shot_id],
                primary_use=shot.visual_purpose,
                secondary_uses=[],
                required_reuse_count=1,
                factual_scope=_dedupe(claim_scope),
                factual_context_id=shot.chapter_id or f"context_{index:02d}",
                source_duration_seconds=strategy.source_video_duration_seconds,
                loopable=category == "atmosphere",
                maximum_continuous_use_seconds=25 if category == "atmosphere" else 15,
                allowed_operations=[],
                crop_regions=_default_crop_regions(category),
                continuity_requirements=[
                    "preserve the approved project time, lighting, identity, and physical geometry"
                ],
                prohibited_details=[
                    "unsupported damage",
                    "unsupported weather",
                    "location labels",
                    "embedded text",
                ],
                camera_stationary=category == "atmosphere",
                seamless_loop_required=category == "atmosphere",
                reconstruction_disclosure=(
                    DisclosureLabel(required=True) if category == "investigation" else None
                ),
                supported_overlay_families=(
                    ["map", "radar", "timeline", "satellite_arc", "technical_diagram"]
                    if category == "investigation"
                    else []
                ),
                major_story_moment=category == "hero",
                reuse_rationale=(
                    "The package is designed as a reusable visual vocabulary item whose factual "
                    "scope and continuity requirements match every linked editorial beat."
                ),
            )
            asset = _category_defaults(asset, strategy)
            assets.append(asset)
            category_assets[category].append(asset)

    non_empty_pools = [pool for pool in category_assets.values() if pool]
    if not non_empty_pools:
        raise ValueError("master-footage strategy produced no generated packages")
    counters = defaultdict(int)
    for shot in skeleton.shots:
        category = _assigned_category(shot)
        pool = category_assets.get(category) or non_empty_pools[0]
        asset = pool[counters[category] % len(pool)]
        counters[category] += 1
        if shot.shot_id not in asset.linked_shots:
            asset.linked_shots.append(shot.shot_id)
        asset.factual_scope = _dedupe([*asset.factual_scope, *shot.claim_ids])
        asset.required_reuse_count = len(asset.linked_shots)
        if shot.visual_purpose not in asset.secondary_uses and shot.visual_purpose != asset.primary_use:
            asset.secondary_uses.append(shot.visual_purpose)

    return MasterAssetPlan(
        project_id=skeleton.project_id,
        maximum_assets=brief.maximum_master_assets,
        strategy=strategy.model_copy(deep=True),
        assets=assets,
        uncovered_shots=[],
    )


def _load_script(project: Path) -> DocumentaryScript:
    path = project / "03_narration/narration.json"
    if not path.exists():
        path = project / "03_script/script.json"
    return load_model(path, DocumentaryScript)


def plan_master_footage(
    store: ProjectStore,
    project_id: str,
    *,
    agent_kind: str = "routed",
    consume_response: bool = False,
) -> MasterAssetPlan:
    project = store.project_dir(project_id)
    brief = store.brief(project_id)
    skeleton = load_model(project / "06_shots/shot_skeleton.json", ShotSkeletonPlan)
    from .models import AudioTiming
    timing = load_model(project / "05_timing/audio_timing.json", AudioTiming)
    if skeleton.voiceover_sha256 != timing.voiceover_sha256:
        raise RuntimeError("shot skeleton does not match the current approved voiceover")
    version = store.next_version(project_id, "master_footage")
    store.transition(project_id, ProjectState.MASTER_PLAN_GENERATING)
    if agent_kind in {"deterministic", "mock"}:
        proposal = deterministic_master_plan(brief, skeleton)
    else:
        research = load_model(project / "01_research/source_dossier.json", ResearchDossier)
        script = _load_script(project)
        context = {
            "project_id": project_id,
            "title": brief.title,
            "duration": brief.target_duration_seconds,
            "research": research,
            "script": script,
            "shot_skeleton": skeleton,
            "master_footage_strategy": brief.master_footage_strategy,
        }
        agent = get_agent(agent_kind, context, consume_response)
        proposal = agent.run(
            stage="master_footage",
            prompt=render_prompt(
                "master_footage",
                brief=brief,
                research=research,
                script=script,
                shot_skeleton=skeleton,
                strategy=brief.master_footage_strategy,
            ),
            output_model=MasterAssetPlan,
            request_dir=project / "_requests",
        )
    proposal = normalize_master_plan(
        proposal,
        brief=brief,
        skeleton=skeleton,
        version=version,
    )
    try:
        validate_master_plan(proposal, skeleton, brief)
    except Exception:
        store.transition(project_id, ProjectState.SHOT_SKELETON_APPROVED)
        raise
    root = project / "05_master_assets"
    write_json(versioned_path(root, "master_footage_plan", ".json", version), proposal)
    write_json(root / "master_footage_plan.json", proposal)
    write_json(root / "validation_report.json", {
        "valid": True,
        "version": version,
        "category_counts": dict(Counter(item.category for item in proposal.assets)),
        "asset_count": len(proposal.assets),
        "covered_shots": len(skeleton.shots) - len(proposal.uncovered_shots),
        "uncovered_shots": proposal.uncovered_shots,
    })
    store.transition(project_id, ProjectState.MASTER_PLAN_REVIEW)
    return proposal


def approve_master_footage(store: ProjectStore, project_id: str) -> MasterAssetPlan:
    project = store.project_dir(project_id)
    brief = store.brief(project_id)
    skeleton = load_model(project / "06_shots/shot_skeleton.json", ShotSkeletonPlan)
    plan = load_model(project / "05_master_assets/master_footage_plan.json", MasterAssetPlan)
    validate_master_plan(plan, skeleton, brief)
    store.approve_version(project_id, "master_footage", plan.plan_version)
    approved = plan.model_copy(deep=True)
    approved.status = "approved"
    write_json(
        project / "05_master_assets" / f"master_footage_plan_v{plan.plan_version:02d}_approved.json",
        approved,
    )
    write_json(project / "05_master_assets/approved_master_footage_plan.json", approved)
    # Compatibility path now points to the approved package specification, not a semantic cluster.
    write_json(project / "05_master_assets/master_assets.json", approved)
    store.transition(project_id, ProjectState.MASTER_PLAN_APPROVED)
    return approved


def approved_master_plan(project_dir: Path) -> MasterAssetPlan:
    project_dir = Path(project_dir)
    path = project_dir / "05_master_assets/approved_master_footage_plan.json"
    if not path.exists():
        path = project_dir / "05_master_assets/master_assets.json"
    plan = load_model(path, MasterAssetPlan)
    if plan.status not in {"approved", "legacy"}:
        raise RuntimeError("approve the master-footage plan before using it downstream")
    return plan


def migrate_legacy_visual_plan(store: ProjectStore, project_id: str) -> MasterAssetPlan:
    """Create a versioned 24-package proposal without touching legacy media or approvals."""
    project = store.project_dir(project_id)
    skeleton_path = project / "06_shots/shot_skeleton.json"
    if not skeleton_path.exists():
        legacy_path = project / "06_shots/shot_plan.json"
        if not legacy_path.exists():
            legacy_path = project / "04_shot_plan/shot_plan.json"
        legacy = load_model(legacy_path, ShotPlan)
        skeleton = ShotSkeletonPlan(
            project_id=legacy.project_id,
            total_seconds=legacy.total_seconds,
            voiceover_sha256=legacy.voiceover_sha256,
            timing_source="migrated_legacy_audio_led_plan",
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
                for item in legacy.shots
            ],
        )
        write_json(skeleton_path, skeleton)
    else:
        skeleton = load_model(skeleton_path, ShotSkeletonPlan)

    brief = store.brief(project_id)
    proposal = deterministic_master_plan(brief, skeleton)
    old_path = project / "05_master_assets/master_assets.json"
    if old_path.exists():
        old = read_json(old_path)
        proposal.migration_notes.append(
            f"Preserved legacy master-assets artifact with {len(old.get('assets', []))} assets."
        )
        proposal.migration_notes.append(
            "Old visual directions were retained as migration context; ambiguous assignments "
            "must be reviewed before approval."
        )
    version = store.next_version(project_id, "master_footage")
    proposal = normalize_master_plan(proposal, brief=brief, skeleton=skeleton, version=version)
    validate_master_plan(proposal, skeleton, brief)
    write_json(
        versioned_path(project / "05_master_assets", "master_footage_plan", ".json", version),
        proposal,
    )
    write_json(project / "05_master_assets/master_footage_plan.json", proposal)
    store.transition(project_id, ProjectState.MASTER_PLAN_REVIEW)
    return proposal
