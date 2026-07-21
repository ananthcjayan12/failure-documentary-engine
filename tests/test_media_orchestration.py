from __future__ import annotations

from pathlib import Path

import pytest

from fde.demo import create_demo
from fde.io import load_model, write_json
from fde.models import MasterAssetPlan, ProjectBrief, Timeline, TimelineEntry
from fde.orchestrator import default_orchestrator_config, public_payload, resolve_task
from fde.project import ProjectStore
from fde.providers.media_factory import generate_project_media
from fde.rendering.composition import build


def test_capability_routing_exposes_grok_media_and_hyperframes():
    config = default_orchestrator_config()
    image = resolve_task(config, "image_generator")
    video = resolve_task(config, "video_generator")
    render = resolve_task(config, "composition_renderer")
    assert image["provider"] == "grok_cli"
    assert image["provider_adapter"] == "grok_cli"
    assert image["capability"] == "image"
    assert video["provider"] == "grok_cli"
    assert video["capability"] == "video"
    assert render["provider"] == "hyperframes"
    assert render["capability"] == "render"
    payload = public_payload(config)
    grok = next(item for item in payload["provider_catalog"] if item["id"] == "grok_cli")
    assert set(grok["capabilities"]) == {"structured", "image", "video"}


def test_incompatible_provider_is_rejected():
    config = default_orchestrator_config()
    config["tasks"]["image_generator"]["provider"] = "codex"
    with pytest.raises(ValueError, match="cannot execute image"):
        resolve_task(config, "image_generator")


def test_mock_media_generation_is_asset_resumable(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    project_dir = create_demo(store, "media-demo")
    plan_path = project_dir / "05_master_assets/master_assets.json"
    plan = load_model(plan_path, MasterAssetPlan)
    for asset in plan.assets:
        asset.approved_image = None
        asset.image_version = 0
    write_json(plan_path, plan)
    route = {
        "provider": "mock", "model": "Deterministic Demo", "retry_count": 0,
        "timeout_seconds": 60, "fallback_provider": "mock",
        "fallback_model": "Deterministic Demo", "media_command_template": "",
        "fallback_media_command_template": "",
    }
    first = generate_project_media(project_dir, media_type="image", route=route)
    assert len(first["generated"]) == len(plan.assets)
    assert not first["failed"]
    second = generate_project_media(project_dir, media_type="image", route=route)
    assert not second["generated"]
    assert len(second["skipped"]) == len(plan.assets)
    state = project_dir / "08_generated_images/generation_state.json"
    assert state.exists()


def test_hyperframes_composition_contract(tmp_path: Path):
    project = tmp_path / "project"
    (project / "00_input").mkdir(parents=True)
    (project / "12_timeline").mkdir(parents=True)
    write_json(project / "00_input/project_brief.json", ProjectBrief(
        project_id="hf-demo", title="HyperFrames Demo", topic="Test", target_duration_seconds=60,
    ))
    write_json(project / "12_timeline/timeline.json", Timeline(
        project_id="hf-demo", total_seconds=5,
        entries=[TimelineEntry(
            timeline_id="T001", shot_id="S001", start=0, end=5, narration_ids=["N001"],
            master_asset="A01", source_media="", media_kind="placeholder",
        )],
    ))
    index = build(project, preview=True, width=1600, height=900, fps=24)
    html = index.read_text(encoding="utf-8")
    assert 'data-composition-id="failure-documentary"' in html
    assert "window.addEventListener('hf-seek'" in html
    assert "window.__hf_ready__=true" in html
    assert (index.parent / "composition-manifest.json").exists()


def test_routed_structured_agent_can_fallback_across_adapters(tmp_path: Path, monkeypatch):
    from fde.agents import RoutedAgent
    from fde.models import ResearchDossier

    monkeypatch.setenv("FDE_LLM_PROVIDER", "custom_cli")
    monkeypatch.setenv("FDE_PROVIDER_ADAPTER", "command")
    monkeypatch.setenv("FDE_LLM_COMMAND", "false")
    monkeypatch.setenv("FDE_LLM_MODEL", "broken")
    monkeypatch.setenv("FDE_LLM_RETRIES", "0")
    monkeypatch.setenv("FDE_LLM_FALLBACK_PROVIDER", "mock")
    monkeypatch.setenv("FDE_LLM_FALLBACK_ADAPTER", "mock")
    monkeypatch.setenv("FDE_LLM_FALLBACK_MODEL", "Deterministic Demo")
    agent = RoutedAgent({"project_id": "route-demo", "title": "Route Demo", "duration": 480})
    result = agent.run(
        stage="research", prompt="Test", output_model=ResearchDossier,
        request_dir=tmp_path / "requests",
    )
    assert result.project_id == "route-demo"
    assert "Offline demonstration dossier" in result.summary


def test_hyperframes_chunk_windows_align_to_timeline_entries():
    from fde.rendering.hyperframes import chunk_windows
    timeline = Timeline(
        project_id="chunks", total_seconds=75,
        entries=[
            TimelineEntry(timeline_id="T1", shot_id="S1", start=0, end=20, narration_ids=[], master_asset="A1", source_media="", media_kind="placeholder"),
            TimelineEntry(timeline_id="T2", shot_id="S2", start=20, end=45, narration_ids=[], master_asset="A2", source_media="", media_kind="placeholder"),
            TimelineEntry(timeline_id="T3", shot_id="S3", start=45, end=75, narration_ids=[], master_asset="A3", source_media="", media_kind="placeholder"),
        ],
    )
    assert chunk_windows(timeline, max_seconds=30) == [(0.0, 20.0), (20.0, 45.0), (45.0, 75.0)]


def _fake_grok(path: Path) -> Path:
    script = path / "grok"
    script.write_text(
        """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args=sys.argv
prompt=args[args.index('-p')+1] if '-p' in args else ''
cwd=Path(args[args.index('--cwd')+1]) if '--cwd' in args else Path.cwd()
if 'JSON SCHEMA' in prompt:
    print(json.dumps({'type':'text','data':'{\"project_id\":\"fake\",\"value\":7}'}))
else:
    out=cwd/'fake-grok-image.png'
    out.write_bytes(bytes.fromhex('89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de0000000c4944415408d763f8ffff3f0005fe02fe0d21bf410000000049454e44ae426082'))
    print(json.dumps({'type':'tool_result','data':{'path':str(out)}}))
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def test_grok_streaming_json_and_media_discovery(tmp_path: Path, monkeypatch):
    from fde.providers.grok_cli import generate_media, run_structured
    binary = _fake_grok(tmp_path)
    monkeypatch.setenv("FDE_GROK_BIN", str(binary))
    structured = run_structured(
        prompt="Return the object", schema={"type":"object"},
        destination=tmp_path/"result.json", cwd=tmp_path,
    )
    assert structured == {"project_id":"fake", "value":7}
    media = generate_media(
        prompt="A documentary still", destination=tmp_path/"approved.png",
        media_type="image", cwd=tmp_path,
    )
    assert Path(media["path"]).exists()
    assert (tmp_path/"grok-cli-output.jsonl").exists()
