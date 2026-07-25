from pathlib import Path

from fde import pipeline
from fde.agents import RoutedAgent
from fde.compact_planning import (
    ClaudePackageDetail,
    ClaudePackageDetailBatch,
    MasterVocabularyOutline,
    build_compact_shot_index,
    deterministic_details,
    deterministic_outline,
)
from fde.io import read_json, write_json
from fde.master_planning import _expand_claude_details, plan_master_footage
from fde.models import AudioTiming, ProjectBrief, ProjectState, ShotSkeleton, ShotSkeletonPlan
from fde.project import ProjectStore


def _skeleton() -> ShotSkeletonPlan:
    shots = [
        ShotSkeleton(
            shot_id=f"SHOT_{index:03d}", chapter_id="CH01", narration_ids=["paragraph_01"],
            claim_ids=["CLM_001"], start=(index - 1) * 5, end=index * 5, duration=5,
            narration_text=f"Narration {index}", visual_purpose="Explain the evidence",
            story_function="evidence_explanation", factual_scope=["CLM_001"],
        )
        for index in range(1, 25)
    ]
    return ShotSkeletonPlan(project_id="compact", shots=shots, total_seconds=120, voiceover_sha256="voice")


def test_pipeline_uses_compact_planner_regardless_of_package_import_order():
    assert pipeline.plan_master_footage is plan_master_footage


def test_detail_claim_scope_is_copied_from_approved_outline():
    outline = deterministic_outline(
        build_compact_shot_index(_skeleton()),
        ProjectBrief(project_id="compact", title="Compact", topic="Test").master_footage_strategy,
    )
    requested = [item for item in outline.packages if item.category == "hero"]
    response = ClaudePackageDetailBatch(
        category="hero",
        packages=[
            ClaudePackageDetail(
                asset_id=item.asset_id,
                visual_concept="Approved visual treatment",
                crop_regions=["wide", "detail"],
            )
            for item in requested
        ],
    )

    batch = _expand_claude_details(response, requested)

    assert [item.factual_scope for item in batch.packages] == [
        item.supported_claim_ids for item in requested
    ]


def test_routed_agent_persists_and_can_reuse_structured_response(monkeypatch, tmp_path: Path):
    response = {"project_id": "compact", "packages": []}
    agent = RoutedAgent({"project_id": "compact", "title": "Compact"})
    monkeypatch.setattr(agent, "_execute", lambda **_kwargs: response)

    result = agent.run(
        stage="outline", prompt="Return JSON", output_model=MasterVocabularyOutline, request_dir=tmp_path,
    )

    assert result.model_dump(mode="json") == response
    assert read_json(tmp_path / "outline_response.json") == response

    cached = RoutedAgent({"project_id": "compact", "title": "Compact"}, consume_response=True)
    monkeypatch.setattr(cached, "_execute", lambda **_kwargs: (_ for _ in ()).throw(AssertionError()))
    assert cached.run(
        stage="outline", prompt="Return JSON", output_model=MasterVocabularyOutline, request_dir=tmp_path,
    ).model_dump(mode="json") == response


def test_master_planner_reuses_saved_outline_and_detail_batches(monkeypatch, tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    project = store.create(ProjectBrief(project_id="compact", title="Compact", topic="Test"))
    skeleton = _skeleton()
    write_json(project / "06_shots/shot_skeleton.json", skeleton)
    write_json(project / "05_timing/audio_timing.json", AudioTiming(
        project_id="compact", source="test", exact=True, voiceover_sha256="voice",
        audio_duration_seconds=120, paragraphs=[], words=[],
    ))
    write_json(project / "01_research/source_dossier.json", {
        "project_id": "compact", "summary": "Test", "claims": [],
    })
    write_json(project / "03_narration/narration.json", {
        "project_id": "compact", "title": "Compact", "segments": [],
    })
    compact = build_compact_shot_index(skeleton)
    outline = deterministic_outline(compact, store.brief("compact").master_footage_strategy)
    write_json(project / "05_master_assets/master_vocabulary_outline.json", outline)
    for category in ("hero", "atmosphere", "investigation"):
        requested = [item for item in outline.packages if item.category == category]
        write_json(
            project / "05_master_assets" / f"master_package_details_{category}.json",
            deterministic_details(category, requested),
        )

    monkeypatch.setattr(
        "fde.master_planning.get_agent",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should reuse saved data")),
    )

    plan = plan_master_footage(store, "compact", agent_kind="routed", consume_response=True)

    assert len(plan.assets) == 24


def test_routed_master_planning_uses_four_compact_contracts(monkeypatch, tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    project = store.create(ProjectBrief(project_id="compact", title="Compact", topic="Test"))
    skeleton = _skeleton()
    write_json(project / "06_shots/shot_skeleton.json", skeleton)
    write_json(project / "05_timing/audio_timing.json", AudioTiming(
        project_id="compact", source="test", exact=True, voiceover_sha256="voice",
        audio_duration_seconds=120, paragraphs=[], words=[],
    ))
    write_json(project / "01_research/source_dossier.json", {
        "project_id": "compact", "summary": "Test", "claims": [{
            "claim_id": "CLM_001", "statement": "Evidence", "status": "confirmed",
        }],
    })
    write_json(project / "03_narration/narration.json", {
        "project_id": "compact", "title": "Compact", "segments": [{
            "narration_id": "paragraph_01", "chapter_id": "CH01", "text": "Evidence", "estimated_duration": 120,
        }],
    })
    compact = build_compact_shot_index(skeleton)
    outline = deterministic_outline(compact, store.brief("compact").master_footage_strategy)
    responses = [outline]
    responses.extend(
        deterministic_details(category, [item for item in outline.packages if item.category == category])
        for category in ("hero", "atmosphere", "investigation")
    )
    calls: list[tuple[str, str]] = []

    class FakeClaude:
        def run(self, *, stage, output_model, **_kwargs):
            calls.append((stage, output_model.__name__))
            return responses.pop(0)

    monkeypatch.setattr("fde.master_planning.get_agent", lambda *_args, **_kwargs: FakeClaude())
    plan = plan_master_footage(store, "compact", agent_kind="routed")

    assert len(plan.assets) == 24
    assert calls == [
        ("master_vocabulary_outline", "MasterVocabularyOutline"),
        ("master_package_details_hero", "ClaudePackageDetailBatch"),
        ("master_package_details_atmosphere", "ClaudePackageDetailBatch"),
        ("master_package_details_investigation", "ClaudePackageDetailBatch"),
    ]
    assert store.manifest("compact").state is ProjectState.MASTER_PLAN_REVIEW
    assert not (project / "_requests/master_footage_schema.json").exists()
