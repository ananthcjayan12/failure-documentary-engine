from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from fde.demo import create_demo
from fde.io import load_model, write_json
from fde.models import MasterAssetPlan, ProjectBrief, Timeline, TimelineEntry
from fde.orchestrator import default_orchestrator_config, public_payload, resolve_task
from fde.project import ProjectStore
from fde.providers.media_factory import generate_project_media
from fde.rendering.composition import build


def test_capability_routing_exposes_verified_media_audio_and_render_options():
    config = default_orchestrator_config()
    image = resolve_task(config, "image_generator")
    video = resolve_task(config, "video_generator")
    voice = resolve_task(config, "voice_generator")
    render = resolve_task(config, "composition_renderer")
    assert image["provider"] == "grok_cli"
    assert image["provider_adapter"] == "grok_cli"
    assert image["model"] == "grok-imagine-image-quality"
    assert image["resolution"] == "2K"
    assert video["provider"] == "grok_cli"
    assert video["model"] == "grok-imagine-video-1.5"
    assert video["resolution"] == "720p"
    assert voice["provider"] == "google_tts"
    assert voice["voice"] == "Kore"
    assert render["provider"] == "ffmpeg"
    assert render["capability"] == "render"
    payload = public_payload(config)
    grok = next(item for item in payload["provider_catalog"] if item["id"] == "grok_cli")
    assert set(grok["capabilities"]) == {"structured", "image", "video"}
    assert grok["options"]["video"]["resolutions_by_model"]["grok-imagine-video-1.5"] == ["480p", "720p", "1080p"]
    gemini = next(item for item in payload["provider_catalog"] if item["id"] == "gemini_api")
    assert "4K" in gemini["options"]["image"]["resolutions_by_model"]["gemini-3.1-flash-image"]
    assert payload["docs_checked_at"] == "2026-07-23"


def test_incompatible_provider_and_model_settings_are_rejected():
    config = default_orchestrator_config()
    config["tasks"]["image_generator"]["provider"] = "codex"
    with pytest.raises(ValueError, match="cannot execute image"):
        resolve_task(config, "image_generator")

    config = default_orchestrator_config()
    config["tasks"]["video_generator"].update({
        "provider": "grok_cli", "model": "grok-imagine-video",
        "resolution": "1080p", "duration_seconds": 8,
    })
    with pytest.raises(ValueError, match="Resolution 1080p"):
        resolve_task(config, "video_generator")


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
        "fallback_media_command_template": "", "resolution": "1K",
        "quality": "standard", "aspect_ratio": "16:9",
    }
    first = generate_project_media(project_dir, media_type="image", route=route)
    assert len(first["generated"]) == len(plan.assets)
    assert first["resolution"] == "1K"
    assert not first["failed"]
    second = generate_project_media(project_dir, media_type="image", route=route)
    assert not second["generated"]
    assert len(second["skipped"]) == len(plan.assets)
    assert (project_dir / "08_generated_images/generation_state.json").exists()


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


def test_anthropic_api_adapter_uses_structured_output(monkeypatch):
    from fde.providers import anthropic_api

    captured = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def read(self): return json.dumps({"content": [{"type": "text", "text": '{"answer":"ok"}'}]}).encode()

    def fake_urlopen(request, timeout):
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(anthropic_api, "urlopen", fake_urlopen)
    result = anthropic_api.run_structured(
        prompt="Return JSON", schema={"type": "object"}, model="claude-sonnet-5",
        timeout=30, reasoning_effort="high",
    )
    assert result == {"answer": "ok"}
    schema = captured["payload"]["output_config"]["format"]["schema"]
    assert captured["payload"]["output_config"]["format"]["type"] == "json_schema"
    assert schema["additionalProperties"] is False
    assert captured["payload"]["model"] == "claude-sonnet-5"
    assert "temperature" not in captured["payload"]
    assert captured["timeout"] == 30


def test_anthropic_api_adapter_makes_nested_objects_strict(monkeypatch):
    from fde.providers import anthropic_api

    captured = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def read(self): return json.dumps({"content": [{"type": "text", "text": "{}"}]}).encode()

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        return Response()

    schema = {
        "type": "object",
        "properties": {
            "items": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string", "minLength": 1}}}},
            "score": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
        },
        "$defs": {"metadata": {"type": "object", "properties": {"id": {"type": "string"}}}},
    }
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(anthropic_api, "urlopen", fake_urlopen)
    anthropic_api.run_structured(prompt="Return JSON", schema=schema, model="claude-sonnet-5", timeout=30)
    strict = captured["payload"]["output_config"]["format"]["schema"]
    assert strict["additionalProperties"] is False
    assert strict["properties"]["items"]["items"]["additionalProperties"] is False
    assert strict["$defs"]["metadata"]["additionalProperties"] is False
    assert "minLength" not in strict["properties"]["items"]["items"]["properties"]["name"]
    assert "exclusiveMinimum" not in strict["properties"]["score"]
    assert "additionalProperties" not in schema


def test_kimi_api_adapter_uses_json_mode(monkeypatch):
    from fde.providers import kimi_api

    captured = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def read(self):
            return json.dumps({"choices": [{"message": {"content": '{"answer":"kimi"}'}}]}).encode()

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setenv("MOONSHOT_API_KEY", "test-key")
    monkeypatch.setattr(kimi_api, "urlopen", fake_urlopen)
    result = kimi_api.run_structured(
        prompt="Return JSON", schema={"type": "object"}, model="kimi-k3",
        timeout=45, reasoning_effort="max",
    )
    assert result == {"answer": "kimi"}
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert captured["payload"]["reasoning_effort"] == "max"
    assert captured["timeout"] == 45


def _fake_gemini(path: Path) -> Path:
    script = path / "gemini"
    script.write_text(
        """#!/usr/bin/env python3
import json, sys
print(json.dumps({'response':'{\"answer\":\"gemini-cli\"}','stats':{'models':{}},'error':None}))
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def test_gemini_cli_adapter_parses_documented_json_envelope(tmp_path: Path, monkeypatch):
    from fde.providers.gemini_cli import run_structured

    binary = _fake_gemini(tmp_path)
    monkeypatch.setenv("FDE_GEMINI_BIN", str(binary))
    result = run_structured(
        prompt="Return JSON", schema={"type": "object"}, destination=tmp_path / "result.json",
        cwd=tmp_path, model="flash", timeout=30,
    )
    assert result == {"answer": "gemini-cli"}
    assert json.loads((tmp_path / "result.json").read_text()) == result
    assert (tmp_path / "gemini-cli-output.log").exists()


def test_openai_image_adapter_persists_selected_size_and_quality(tmp_path: Path, monkeypatch):
    from fde.providers import openai_image_api

    captured = {}
    png = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de0000000c4944415408d763f8ffff3f0005fe02fe0d21bf410000000049454e44ae426082")

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def read(self): return json.dumps({"data": [{"b64_json": base64.b64encode(png).decode()}]}).encode()

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        return Response()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(openai_image_api, "urlopen", fake_urlopen)
    destination = tmp_path / "image.png"
    result = openai_image_api.generate_image(
        prompt="Documentary image", destination=destination, model="gpt-image-2",
        resolution="1536x1024", quality="high", timeout=30,
    )
    assert destination.exists()
    assert result["resolution"] == "1536x1024"
    assert captured["payload"]["quality"] == "high"
    assert captured["payload"]["size"] == "1536x1024"


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
import json, sys
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
        prompt="Return the object", schema={"type": "object"},
        destination=tmp_path / "result.json", cwd=tmp_path,
    )
    assert structured == {"project_id": "fake", "value": 7}
    media = generate_media(
        prompt="A documentary still", destination=tmp_path / "approved.png",
        media_type="image", cwd=tmp_path, model="grok-imagine-image-quality",
        resolution="2K", quality="quality",
    )
    assert Path(media["path"]).exists()
    assert media["resolution"] == "2K"
    assert (tmp_path / "grok-cli-output.jsonl").exists()
