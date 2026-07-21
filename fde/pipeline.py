from __future__ import annotations

from pathlib import Path

from .agents import get_agent
from .io import load_model, versioned_path, write_json
from .models import (
    DocumentaryScript,
    DocumentaryStructure,
    ProjectState,
    ResearchDossier,
    ShotPlan,
)
from .project import ProjectStore
from .prompts import render_prompt
from .reports import research_markdown, script_markdown, shots_markdown, structure_markdown


def _context(store: ProjectStore, project_id: str) -> dict:
    brief = store.brief(project_id)
    return {
        "project_id": project_id,
        "title": brief.title,
        "duration": brief.target_duration_seconds,
    }


def generate_research(store: ProjectStore, project_id: str, agent_kind: str, consume_response: bool = False) -> ResearchDossier:
    brief = store.brief(project_id)
    agent = get_agent(agent_kind, _context(store, project_id), consume_response)
    dossier = agent.run(
        stage="research", prompt=render_prompt("research", brief=brief),
        output_model=ResearchDossier, request_dir=store.project_dir(project_id) / "_requests",
    )
    version = store.next_version(project_id, "research")
    out = versioned_path(store.project_dir(project_id) / "01_research", "source_dossier", ".json", version)
    write_json(out, dossier)
    write_json(store.project_dir(project_id) / "01_research/source_dossier.json", dossier)
    write_json(store.project_dir(project_id) / "01_research/claim_ledger.json", {"claims": dossier.claims})
    (store.project_dir(project_id) / "01_research/source_summary.md").write_text(research_markdown(dossier), encoding="utf-8")
    store.transition(project_id, ProjectState.RESEARCH_READY)
    return dossier


def generate_structure(store: ProjectStore, project_id: str, agent_kind: str, consume_response: bool = False) -> DocumentaryStructure:
    brief = store.brief(project_id)
    research = load_model(store.project_dir(project_id) / "01_research/source_dossier.json", ResearchDossier)
    context = _context(store, project_id) | {"research": research}
    agent = get_agent(agent_kind, context, consume_response)
    structure = agent.run(
        stage="structure", prompt=render_prompt("structure", brief=brief, research=research),
        output_model=DocumentaryStructure, request_dir=store.project_dir(project_id) / "_requests",
    )
    version = store.next_version(project_id, "structure")
    write_json(versioned_path(store.project_dir(project_id) / "02_structure", "structure", ".json", version), structure)
    write_json(store.project_dir(project_id) / "02_structure/structure.json", structure)
    (store.project_dir(project_id) / "02_structure/structure.md").write_text(structure_markdown(structure), encoding="utf-8")
    store.transition(project_id, ProjectState.STRUCTURE_REVIEW)
    return structure


def generate_script(store: ProjectStore, project_id: str, agent_kind: str, consume_response: bool = False) -> DocumentaryScript:
    brief = store.brief(project_id)
    research = load_model(store.project_dir(project_id) / "01_research/source_dossier.json", ResearchDossier)
    structure = load_model(store.project_dir(project_id) / "02_structure/structure.json", DocumentaryStructure)
    context = _context(store, project_id) | {"research": research, "structure": structure}
    agent = get_agent(agent_kind, context, consume_response)
    script = agent.run(
        stage="script", prompt=render_prompt("script", brief=brief, structure=structure, research=research),
        output_model=DocumentaryScript, request_dir=store.project_dir(project_id) / "_requests",
    )
    version = store.next_version(project_id, "script")
    write_json(versioned_path(store.project_dir(project_id) / "03_script", "script", ".json", version), script)
    write_json(store.project_dir(project_id) / "03_script/script.json", script)
    (store.project_dir(project_id) / "03_script/script.md").write_text(script_markdown(script), encoding="utf-8")
    store.transition(project_id, ProjectState.SCRIPT_REVIEW)
    return script


def generate_shots(store: ProjectStore, project_id: str, agent_kind: str, consume_response: bool = False) -> ShotPlan:
    brief = store.brief(project_id)
    script = load_model(store.project_dir(project_id) / "03_script/script.json", DocumentaryScript)
    context = _context(store, project_id) | {"script": script}
    agent = get_agent(agent_kind, context, consume_response)
    shots = agent.run(
        stage="shots", prompt=render_prompt("shots", brief=brief, script=script),
        output_model=ShotPlan, request_dir=store.project_dir(project_id) / "_requests",
    )
    version = store.next_version(project_id, "shots")
    write_json(versioned_path(store.project_dir(project_id) / "04_shot_plan", "shot_plan", ".json", version), shots)
    write_json(store.project_dir(project_id) / "04_shot_plan/shot_plan.json", shots)
    (store.project_dir(project_id) / "04_shot_plan/shot_plan.md").write_text(shots_markdown(shots), encoding="utf-8")
    store.transition(project_id, ProjectState.SHOT_PLAN_READY)
    return shots
