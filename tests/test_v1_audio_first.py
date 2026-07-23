from collections import Counter
from pathlib import Path

import pytest

from fde.editorial import approve_editorial_shots, direct_editorial_shots
from fde.io import write_json
from fde.master_footage import approve_master_footage, plan_master_footage
from fde.models import DocumentaryScript, NarrationSegment, ProjectBrief
from fde.narration import clean_spoken_text, generate_voice, validate_tagged_text
from fde.project import ProjectStore
from fde.shots import plan_shots
from fde.timing import derive_timing, timing_is_current
from fde.v1_media import (
    approve_media,
    generate_media_jobs,
    prepare_media_jobs,
    render_animatic,
    render_final_preview,
)


def test_audio_first_two_pass_mock_pipeline(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    project = store.create(
        ProjectBrief(
            project_id="demo",
            title="Demo",
            topic="Failure",
            target_duration_seconds=60,
            maximum_master_assets=24,
        )
    )
    script = DocumentaryScript(
        project_id="demo",
        title="Demo",
        segments=[
            NarrationSegment(
                narration_id="paragraph_01",
                chapter_id="CH01",
                text="[quietly investigative] The first signal vanished without warning.",
                estimated_duration=4,
                claim_ids=["C1"],
            ),
            NarrationSegment(
                narration_id="paragraph_02",
                chapter_id="CH01",
                text="Investigators then found a second, more troubling clue.",
                estimated_start=4,
                estimated_duration=4,
                claim_ids=["C1"],
            ),
        ],
    )
    write_json(project / "03_narration/narration.json", script)
    manifest = generate_voice(project, provider="mock")
    assert manifest.chapters[0].tagged_text.startswith("[quietly investigative]")
    assert clean_spoken_text(manifest.chapters[0].tagged_text).startswith("The first")

    timing = derive_timing(project)
    assert timing.exact is True and timing.words
    assert timing_is_current(project)
    skeleton = plan_shots(project, minimum=1, target=3, maximum=5)
    assert skeleton.voiceover_sha256 == manifest.voiceover_sha256
    assert skeleton.shots[0].start == 0
    legacy = __import__("json").loads((project / "06_shots/shot_plan.json").read_text())
    assert all(not item["image_prompt"] and not item["video_prompt"] for item in legacy["shots"])

    master = plan_master_footage(store, "demo", agent_kind="deterministic")
    assert len(master.assets) == 24
    assert Counter(item.category for item in master.assets) == {
        "hero": 8,
        "atmosphere": 8,
        "investigation": 8,
    }
    assert [item.asset_id for item in master.assets[:8]] == [f"H{i:02d}" for i in range(1, 9)]
    assert [item.asset_id for item in master.assets[8:16]] == [f"L{i:02d}" for i in range(1, 9)]
    assert [item.asset_id for item in master.assets[16:]] == [f"E{i:02d}" for i in range(1, 9)]
    approve_master_footage(store, "demo")

    editorial = direct_editorial_shots(store, "demo", agent_kind="deterministic")
    assert [item.shot_id for item in editorial.shots] == [item.shot_id for item in skeleton.shots]
    assert [(item.start, item.end) for item in editorial.shots] == [
        (item.start, item.end) for item in skeleton.shots
    ]
    approve_editorial_shots(store, "demo")

    images = prepare_media_jobs(project, "image")
    assert len(images.jobs) == 24
    assert {job.category for job in images.jobs} == {"hero", "atmosphere", "investigation"}
    images = generate_media_jobs(
        project,
        media_type="image",
        route={
            "provider": "mock",
            "model": "demo",
            "timeout": 30,
            "command": "",
            "resolution": "1K",
            "aspect_ratio": "16:9",
        },
    )
    assert all(job.status == "review" for job in images.jobs)
    images = approve_media(project, media_type="image")
    assert all(job.status == "approved" for job in images.jobs)

    animatic = render_animatic(project)
    assert (project / animatic.output).exists()
    videos = prepare_media_jobs(project, "video")
    assert len(videos.jobs) == 24
    assert all(job.duration_seconds == 5 for job in videos.jobs)
    videos = approve_media(project, media_type="video")
    assert all(job.status == "rejected" for job in videos.jobs)
    final = render_final_preview(project)
    assert final.exists() and final.stat().st_size > 1000


def test_rejects_unsupported_or_multiple_tags():
    with pytest.raises(ValueError):
        validate_tagged_text("[epic] This should fail.")
    with pytest.raises(ValueError):
        validate_tagged_text("[serious] [curious] Too many tags.")
