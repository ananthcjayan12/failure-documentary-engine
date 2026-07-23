from pathlib import Path
from fde.io import write_json
from fde.models import DocumentaryScript, NarrationSegment, ProjectBrief
from fde.narration import clean_spoken_text, generate_voice
from fde.project import ProjectStore
from fde.timing import derive_timing, timing_is_current
from fde.shots import plan_shots
from fde.v1_media import prepare_media_jobs, generate_media_jobs, approve_media, render_animatic, render_final_preview


def test_audio_first_mock_pipeline(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    project = store.create(ProjectBrief(project_id="demo", title="Demo", topic="Failure", target_duration_seconds=60))
    script = DocumentaryScript(project_id="demo", title="Demo", segments=[
        NarrationSegment(narration_id="paragraph_01", chapter_id="CH01", text="[quietly investigative] The first signal vanished without warning.", estimated_duration=4, claim_ids=["C1"]),
        NarrationSegment(narration_id="paragraph_02", chapter_id="CH01", text="Investigators then found a second, more troubling clue.", estimated_start=4, estimated_duration=4, claim_ids=["C1"]),
    ])
    write_json(project / "03_narration/narration.json", script)
    manifest = generate_voice(project, provider="mock")
    assert manifest.chapters[0].tagged_text.startswith("[quietly investigative]")
    assert clean_spoken_text(manifest.chapters[0].tagged_text).startswith("The first")
    timing = derive_timing(project)
    assert timing.exact is True and timing.words
    assert timing_is_current(project)
    shots = plan_shots(project, minimum=1, target=3, maximum=5)
    assert shots.voiceover_sha256 == manifest.voiceover_sha256
    assert shots.shots[0].start == 0
    images = prepare_media_jobs(project, "image")
    assert len(images.jobs) == len(shots.shots)
    images = generate_media_jobs(project, media_type="image", route={"provider": "mock", "model": "demo", "timeout": 30, "command": ""})
    assert all(job.status == "review" for job in images.jobs)
    images = approve_media(project, media_type="image")
    assert all(job.status == "approved" for job in images.jobs)
    animatic = render_animatic(project)
    assert (project / animatic.output).exists()
    videos = prepare_media_jobs(project, "video")
    videos = approve_media(project, media_type="video")
    assert all(job.status == "rejected" for job in videos.jobs)
    final = render_final_preview(project)
    assert final.exists() and final.stat().st_size > 1000


def test_rejects_unsupported_or_multiple_tags(tmp_path: Path):
    from fde.narration import validate_tagged_text
    import pytest
    with pytest.raises(ValueError):
        validate_tagged_text("[epic] This should fail.")
    with pytest.raises(ValueError):
        validate_tagged_text("[serious] [curious] Too many tags.")
