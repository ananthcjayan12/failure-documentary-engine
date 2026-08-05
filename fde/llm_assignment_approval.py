from __future__ import annotations

from .io import load_model, write_json
from .llm_editorial_assignment import (
    AssignmentEligibilityPlan,
    validate_llm_assignment_plan,
)
from .master_footage import approved_master_plan
from .models import EditorialShotPlan, ProjectState, ShotSkeletonPlan
from .project import ProjectStore


def approve_editorial_shots_llm_all(
    store: ProjectStore,
    project_id: str,
) -> EditorialShotPlan:
    """Approve an LLM-assigned plan using its persisted objective eligibility set."""
    project = store.project_dir(project_id)
    skeleton = load_model(
        project / "06_shots/shot_skeleton.json",
        ShotSkeletonPlan,
    )
    master_plan = approved_master_plan(project)
    plan = load_model(
        project / "06_shots/editorial_shot_plan.json",
        EditorialShotPlan,
    )
    eligibility = load_model(
        project / "06_shots/assignment_eligibility.json",
        AssignmentEligibilityPlan,
    )
    validate_llm_assignment_plan(
        plan,
        skeleton,
        master_plan,
        eligibility,
    )
    version = store.manifest(project_id).current_versions.get("editorial_shots")
    if not version:
        raise RuntimeError("no current editorial-shot version")
    store.approve_version(project_id, "editorial_shots", version)
    write_json(
        project
        / "06_shots"
        / f"editorial_shot_plan_v{version:02d}_approved.json",
        plan,
    )
    store.transition(project_id, ProjectState.SHOTS_APPROVED)
    return plan
