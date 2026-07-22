from __future__ import annotations

from pathlib import Path

from .agents import get_agent
from .io import load_model, versioned_path, write_json
from .models import (
    AudioManifest,
    AudioTiming,
    DocumentaryScript,
    DocumentaryStructure,
    ProjectState,
    ResearchDossier,
    ShotPlan,
)
from .narration import clean_spoken_text, generate_voice, performance_tags, validate_tagged_text
from .project import ProjectStore
from .prompts import render_prompt
from .reports import research_markdown, script_markdown, shots_markdown, structure_markdown
from .shots import plan_shots
from .timing import derive_timing


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


def _normalize_narration(script: DocumentaryScript) -> DocumentaryScript:
    sparse_tags = ["quietly investigative", "curious", "clear and measured", "serious", "reflective"]
    for index, segment in enumerate(script.segments):
        segment.narration_id = f"paragraph_{index + 1:02d}"
        text = segment.text.strip()
        if not performance_tags(text) and (index == 0 or index % 4 == 0):
            text = f"[{sparse_tags[min(index // 4, len(sparse_tags) - 1)]}] {text}"
        validate_tagged_text(text)
        segment.text = text
    script.tts_narration = "\n\n".join(item.text for item in script.segments)
    script.estimated_word_count = sum(len(clean_spoken_text(item.text).split()) for item in script.segments)
    script.estimated_total_seconds = sum(item.estimated_duration for item in script.segments)
    return script


def generate_script(store: ProjectStore, project_id: str, agent_kind: str, consume_response: bool = False) -> DocumentaryScript:
    """Generate the approved spoken narration. Kept as `script` for CLI compatibility."""
    brief = store.brief(project_id)
    research = load_model(store.project_dir(project_id) / "01_research/source_dossier.json", ResearchDossier)
    structure = load_model(store.project_dir(project_id) / "02_structure/structure.json", DocumentaryStructure)
    context = _context(store, project_id) | {"research": research, "structure": structure}
    agent = get_agent(agent_kind, context, consume_response)
    script = agent.run(
        stage="script", prompt=render_prompt("script", brief=brief, structure=structure, research=research),
        output_model=DocumentaryScript, request_dir=store.project_dir(project_id) / "_requests",
    )
    script = _normalize_narration(script)
    version = store.next_version(project_id, "narration")
    project = store.project_dir(project_id)
    write_json(versioned_path(project / "03_narration", "narration", ".json", version), script)
    write_json(project / "03_narration/narration.json", script)
    (project / "03_narration/narration_tagged.txt").write_text(script.tts_narration.rstrip() + "\n", encoding="utf-8")
    (project / "03_narration/narration_clean.txt").write_text(
        "\n\n".join(clean_spoken_text(item.text) for item in script.segments).rstrip() + "\n",
        encoding="utf-8",
    )
    # Compatibility mirror for the existing report and manual-response tools.
    write_json(project / "03_script/script.json", script)
    (project / "03_script/script.md").write_text(script_markdown(script), encoding="utf-8")
    store.transition(project_id, ProjectState.NARRATION_REVIEW)
    return script


def generate_voice_stage(
    store: ProjectStore,
    project_id: str,
    *,
    provider: str = "gemini",
    model: str | None = None,
    voice: str | None = None,
    paragraph_ids: list[str] | None = None,
    force: bool = False,
) -> AudioManifest:
    store.transition(project_id, ProjectState.VOICE_GENERATING)
    manifest = generate_voice(
        store.project_dir(project_id), provider=provider, model=model, voice=voice,
        paragraph_ids=paragraph_ids, force=force,
    )
    store.transition(project_id, ProjectState.VOICE_REVIEW)
    return manifest


def generate_timing_stage(
    store: ProjectStore,
    project_id: str,
    *,
    allow_approximate: bool | None = None,
) -> AudioTiming:
    timing = derive_timing(store.project_dir(project_id), allow_approximate=allow_approximate)
    return timing


def generate_shots(
    store: ProjectStore,
    project_id: str,
    agent_kind: str = "deterministic",
    consume_response: bool = False,
) -> ShotPlan:
    """Plan exact shots from the current generated voice timing.

    `agent_kind` and `consume_response` remain in the signature so existing Studio actions keep
    working, but V1 deliberately uses the deterministic VCJ-style timing compiler.
    """
    del agent_kind, consume_response
    store.transition(project_id, ProjectState.SHOTS_GENERATING)
    shots = plan_shots(store.project_dir(project_id))
    version = store.next_version(project_id, "shots")
    project = store.project_dir(project_id)
    write_json(versioned_path(project / "06_shots", "shot_plan", ".json", version), shots)
    (project / "06_shots/shot_plan.md").write_text(shots_markdown(shots), encoding="utf-8")
    store.transition(project_id, ProjectState.SHOTS_REVIEW)
    return shots
