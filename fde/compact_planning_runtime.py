from __future__ import annotations

from collections import Counter

from .agents import get_agent
from .compact_planning import (
    CATEGORY_ORDER,
    MasterPackageDetailBatch,
    MasterVocabularyOutline,
    _chapter_summaries,
    _claim_ledger,
    _combine_plan,
    _load_script,
    build_compact_shot_index,
    deterministic_details,
    deterministic_outline,
    validate_detail_batch,
    validate_outline,
)
from .io import load_model, versioned_path, write_json
from .master_footage import validate_master_plan
from .models import (
    AudioTiming,
    MasterAssetPlan,
    ProjectState,
    ResearchDossier,
    ShotSkeletonPlan,
)
from .project import ProjectStore
from .prompts import render_prompt


def plan_master_footage_compact_runtime(
    store: ProjectStore,
    project_id: str,
    *,
    agent_kind: str = "routed",
    consume_response: bool = False,
) -> MasterAssetPlan:
    """Run compact planning without requiring research files for offline/deterministic use."""
    project = store.project_dir(project_id)
    brief = store.brief(project_id)
    skeleton = load_model(project / "06_shots/shot_skeleton.json", ShotSkeletonPlan)
    timing = load_model(project / "05_timing/audio_timing.json", AudioTiming)
    if skeleton.voiceover_sha256 != timing.voiceover_sha256:
        raise RuntimeError("shot skeleton does not match the current approved voiceover")
    compact = build_compact_shot_index(skeleton)
    write_json(project / "06_shots/compact_shot_index.json", compact)
    version = store.next_version(project_id, "master_footage")
    store.transition(project_id, ProjectState.MASTER_PLAN_GENERATING)
    deterministic = agent_kind in {"deterministic", "mock"}
    context = {
        "project_id": project_id,
        "title": brief.title,
        "duration": brief.target_duration_seconds,
    }

    try:
        if deterministic:
            outline = deterministic_outline(compact, brief.master_footage_strategy)
            claims: list[dict] = []
        else:
            research = load_model(
                project / "01_research/source_dossier.json",
                ResearchDossier,
            )
            script = _load_script(project)
            chapters = _chapter_summaries(project, script)
            claims = _claim_ledger(research)
            agent = get_agent(agent_kind, context, consume_response)
            outline = agent.run(
                stage="master_vocabulary_outline",
                prompt=render_prompt(
                    "master_vocabulary_outline",
                    brief=brief,
                    chapter_summaries=chapters,
                    claim_ledger=claims,
                    compact_shot_index=compact,
                    strategy=brief.master_footage_strategy,
                ),
                output_model=MasterVocabularyOutline,
                request_dir=project / "_requests",
            )
        validate_outline(outline, compact, brief.master_footage_strategy)
        write_json(
            project / "05_master_assets/master_vocabulary_outline.json",
            outline,
        )

        detail_batches: list[MasterPackageDetailBatch] = []
        for category in CATEGORY_ORDER:
            requested = [
                item for item in outline.packages if item.category == category
            ]
            relevant_shot_ids = {
                shot_id
                for item in requested
                for shot_id in item.supported_shot_ids
            }
            relevant_shots = [
                item for item in compact.shots if item.shot_id in relevant_shot_ids
            ]
            relevant_claim_ids = {
                claim for item in requested for claim in item.supported_claim_ids
            }
            relevant_claims = [
                item for item in claims if item["claim_id"] in relevant_claim_ids
            ]
            if deterministic:
                batch = deterministic_details(category, requested)
            else:
                agent = get_agent(agent_kind, context, consume_response)
                batch = agent.run(
                    stage=f"master_package_details_{category}",
                    prompt=render_prompt(
                        "master_package_details",
                        category=category,
                        approved_outline=outline,
                        requested_packages=requested,
                        relevant_shots=relevant_shots,
                        relevant_claims=relevant_claims,
                        strategy=brief.master_footage_strategy,
                    ),
                    output_model=MasterPackageDetailBatch,
                    request_dir=project / "_requests",
                )
            validate_detail_batch(batch, requested)
            detail_batches.append(batch)
            write_json(
                project
                / "05_master_assets"
                / f"master_package_details_{category}.json",
                batch,
            )

        proposal = _combine_plan(
            outline,
            detail_batches,
            brief=brief,
            skeleton=skeleton,
            version=version,
        )
        validate_master_plan(proposal, skeleton, brief)
    except Exception:
        store.transition(project_id, ProjectState.SHOT_SKELETON_APPROVED)
        raise

    root = project / "05_master_assets"
    write_json(
        versioned_path(root, "master_footage_plan", ".json", version),
        proposal,
    )
    write_json(root / "master_footage_plan.json", proposal)
    write_json(
        root / "validation_report.json",
        {
            "valid": True,
            "version": version,
            "planning_calls": {
                "global_outline": 0 if deterministic else 1,
                "category_detail_batches": 0 if deterministic else 3,
                "full_shot_plan_returned_by_model": False,
            },
            "category_counts": dict(
                Counter(item.category for item in proposal.assets)
            ),
            "asset_count": len(proposal.assets),
            "compact_shot_count": len(compact.shots),
            "covered_shots": len(skeleton.shots),
            "uncovered_shots": [],
        },
    )
    store.transition(project_id, ProjectState.MASTER_PLAN_REVIEW)
    return proposal
