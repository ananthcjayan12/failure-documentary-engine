from __future__ import annotations

from pathlib import Path

import pytest

from fde.io import load_model, write_json
from fde.models import V1MediaJob, V1MediaManifest
from fde.orchestrator import PROVIDERS, default_orchestrator_config, merge_orchestrator_config, resolve_task
from fde.providers.grok_cli import generate_media
from fde.video_duration import compile_video_duration
from fde.v1_media import recover_video_with_local_motion


@pytest.mark.parametrize(
    ("requested", "provider"),
    [(5, 6), (6, 6), (8, 10), (10, 10)],
)
def test_grok_duration_compiler_preserves_edit_duration(requested: float, provider: float):
    plan = compile_video_duration("grok_cli", requested)
    assert plan.requested_duration_seconds == requested
    assert plan.provider_duration_seconds == provider
    assert plan.conform_duration_seconds == requested


def test_grok_duration_compiler_rejects_over_ten_seconds():
    with pytest.raises(ValueError, match="at most 10"):
        compile_video_duration("grok_cli", 11)


def test_orchestrator_exposes_only_valid_grok_durations_and_migrates_legacy_value():
    config = default_orchestrator_config()
    assert config["tasks"]["video_generator"]["duration_seconds"] == 6
    assert PROVIDERS["grok_cli"]["options"]["video"]["duration_seconds"] == [6, 10]

    saved = default_orchestrator_config()
    saved["version"] = 4
    saved["tasks"]["video_generator"].update({"duration_seconds": 8, "resolution": "480p"})
    merged = merge_orchestrator_config(saved)
    assert merged["tasks"]["video_generator"]["duration_seconds"] == 6
    assert merged["tasks"]["video_generator"]["resolution"] == "480p"

    config["tasks"]["video_generator"]["duration_seconds"] = 8
    with pytest.raises(ValueError, match="Duration 8"):
        resolve_task(config, "video_generator")


def test_grok_adapter_rejects_invalid_duration_before_cli_lookup(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("fde.providers.grok_cli.grok_binary", lambda: pytest.fail("CLI must not be called"))
    with pytest.raises(ValueError, match="must be 6 or 10"):
        generate_media(
            prompt="x", destination=tmp_path / "out.mp4", media_type="video", cwd=tmp_path,
            duration=8,
        )


def test_local_recovery_uses_no_provider_and_changes_only_selected_job(monkeypatch, tmp_path: Path):
    project = tmp_path / "project"
    (project / "09_videos").mkdir(parents=True)
    image = project / "07_images/H02/image.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"image")
    manifest = V1MediaManifest(
        project_id="test",
        media_type="video",
        jobs=[
            V1MediaJob(
                job_id="VIDEO_H02", asset_id="H02", media_type="video", status="failed",
                prompt="fallback", output="09_videos/H02/approved.mp4", duration_seconds=6,
            ),
            V1MediaJob(
                job_id="VIDEO_H03", asset_id="H03", media_type="video", status="pending",
                prompt="untouched", output="09_videos/H03/approved.mp4", duration_seconds=6,
            ),
        ],
    )
    write_json(project / "09_videos/jobs.json", manifest)

    def fake_generate_one(**kwargs):
        assert kwargs["provider"] == "local_motion"
        destination = kwargs["destination"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"video")
        return {"provider": "local_motion", "network_calls": 0}

    monkeypatch.setattr("fde.v1_media.generate_one", fake_generate_one)
    monkeypatch.setattr("fde.v1_media._measured_video_duration", lambda path: 6.0)

    recovered = recover_video_with_local_motion(project, "H02")
    assert recovered.jobs[0].status == "review"
    assert recovered.jobs[0].generation_mode == "local_fallback"
    assert recovered.jobs[1].status == "pending"
    saved = load_model(project / "09_videos/jobs.json", V1MediaManifest)
    assert saved.jobs[0].status == "review"
    assert (project / "09_videos/H02/approved.mp4").exists()
