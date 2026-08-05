from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from .agents import AgentPending
from .editorial import approve_editorial_shots
from .io import read_json, safe_copy, write_json
from .master_footage import approve_master_footage
from .media import has_command
from .models import MasterFootageStrategy, ProjectBrief, ProjectState
from .pipeline import (
    generate_editorial_shots_stage,
    generate_master_footage_stage,
    generate_research,
    generate_script,
    generate_shot_skeleton_stage,
    generate_structure,
    generate_timing_stage,
    generate_voice_stage,
)
from .project import ProjectStore
from .v1_media import (
    approve_media,
    generate_media_jobs,
    prepare_media_jobs,
    recover_video_with_local_motion,
    render_animatic,
    render_final_preview,
    transition_after_media,
)

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
app = typer.Typer(help="Failure Documentary Engine — audio-first two-pass production")
console = Console()


def store(workspace: Path) -> ProjectStore:
    return ProjectStore(workspace)


def _run_agent(callable_):
    try:
        result = callable_()
        console.print(f"[green]Created {type(result).__name__}[/green]")
        return result
    except AgentPending as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        raise typer.Exit(code=2)


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@app.command()
def doctor() -> None:
    table = Table("Tool", "Available", "Purpose")
    for name, purpose in [
        ("ffmpeg", "voice assembly, timeline playback, animatic and final preview"),
        ("ffprobe", "final stream validation"),
        ("codex", "optional structured planning agent"),
        ("grok", "optional image and video generation"),
        ("gemini", "optional structured planning agent"),
    ]:
        table.add_row(name, "yes" if has_command(name) else "no", purpose)
    try:
        import google.genai  # noqa: F401
        gemini = "yes"
    except Exception:
        gemini = "no"
    table.add_row("google-genai", gemini, "Gemini TTS, structured, image and video APIs")
    console.print(table)


@app.command()
def init(
    project_id: str,
    title: Annotated[str, typer.Option()] = "Untitled Failure Investigation",
    topic: Annotated[str, typer.Option()] = "",
    duration: Annotated[float, typer.Option()] = 480,
    max_assets: Annotated[int, typer.Option()] = 24,
    hero_assets: Annotated[int, typer.Option()] = 8,
    atmosphere_assets: Annotated[int, typer.Option()] = 8,
    investigation_assets: Annotated[int, typer.Option()] = 8,
    source_video_duration: Annotated[float, typer.Option()] = 5,
    workspace: Annotated[Path, typer.Option()] = Path("projects"),
) -> None:
    strategy = MasterFootageStrategy(
        hero_count=hero_assets,
        atmosphere_count=atmosphere_assets,
        investigation_count=investigation_assets,
        source_video_duration_seconds=source_video_duration,
        target_generated_video_count=hero_assets + atmosphere_assets + investigation_assets,
    )
    brief = ProjectBrief(
        project_id=project_id,
        title=title,
        topic=topic or title,
        target_duration_seconds=duration,
        maximum_master_assets=max_assets,
        master_video_duration_seconds=source_video_duration,
        master_footage_strategy=strategy,
    )
    path = store(workspace).create(brief)
    console.print(f"[green]Created project[/green] {path}")


@app.command()
def research(project_id: str, agent: str = "manual", consume_response: bool = False,
             workspace: Path = Path("projects")) -> None:
    _run_agent(lambda: generate_research(store(workspace), project_id, agent, consume_response))


@app.command()
def structure(project_id: str, agent: str = "manual", consume_response: bool = False,
              workspace: Path = Path("projects")) -> None:
    _run_agent(lambda: generate_structure(store(workspace), project_id, agent, consume_response))


@app.command("narration")
def narration_cmd(project_id: str, agent: str = "manual", consume_response: bool = False,
                  workspace: Path = Path("projects")) -> None:
    _run_agent(lambda: generate_script(store(workspace), project_id, agent, consume_response))


@app.command()
def script(project_id: str, agent: str = "manual", consume_response: bool = False,
           workspace: Path = Path("projects")) -> None:
    narration_cmd(project_id, agent, consume_response, workspace)


@app.command("generate-voice")
def generate_voice_cmd(
    project_id: str,
    provider: str = typer.Option("gemini", help="gemini, elevenlabs, or mock"),
    model: str = typer.Option(""),
    voice: str = typer.Option(""),
    paragraphs: str = typer.Option("", help="Comma-separated paragraph IDs"),
    force: bool = typer.Option(False),
    workspace: Path = Path("projects"),
) -> None:
    manifest = generate_voice_stage(
        store(workspace), project_id, provider=provider, model=model or None,
        voice=voice or None, paragraph_ids=_csv(paragraphs) or None, force=force,
    )
    console.print_json(data=manifest.model_dump(mode="json"))


@app.command("generate-timing")
def generate_timing_cmd(
    project_id: str,
    allow_approximate: bool = typer.Option(False),
    workspace: Path = Path("projects"),
) -> None:
    timing = generate_timing_stage(store(workspace), project_id, allow_approximate=allow_approximate)
    console.print_json(data=timing.model_dump(mode="json"))


@app.command("shot-skeleton")
def shot_skeleton_cmd(project_id: str, workspace: Path = Path("projects")) -> None:
    result = generate_shot_skeleton_stage(store(workspace), project_id)
    console.print_json(data=result.model_dump(mode="json"))


@app.command("master-footage")
def master_footage_cmd(
    project_id: str,
    agent: str = "routed",
    consume_response: bool = False,
    workspace: Path = Path("projects"),
) -> None:
    _run_agent(lambda: generate_master_footage_stage(store(workspace), project_id, agent, consume_response))


@app.command("editorial-shots")
def editorial_shots_cmd(
    project_id: str,
    agent: str = "routed",
    consume_response: bool = False,
    workspace: Path = Path("projects"),
) -> None:
    _run_agent(lambda: generate_editorial_shots_stage(store(workspace), project_id, agent, consume_response))


@app.command("approve-stage")
def approve_stage(project_id: str, stage: str, workspace: Path = Path("projects")) -> None:
    s = store(workspace)
    if stage == "structure":
        s.approve_version(project_id, "structure")
        s.transition(project_id, ProjectState.STRUCTURE_APPROVED)
    elif stage in {"narration", "script"}:
        s.approve_version(project_id, "narration")
        s.transition(project_id, ProjectState.NARRATION_APPROVED)
    elif stage == "voice":
        s.transition(project_id, ProjectState.VOICE_APPROVED)
    elif stage in {"shot_skeleton", "skeleton"}:
        s.approve_version(project_id, "shot_skeleton")
        s.transition(project_id, ProjectState.SHOT_SKELETON_APPROVED)
    elif stage in {"master_footage", "master_plan"}:
        approve_master_footage(s, project_id)
    elif stage in {"shots", "editorial_shots"}:
        approve_editorial_shots(s, project_id)
    elif stage == "images":
        s.transition(project_id, ProjectState.IMAGES_APPROVED)
    elif stage == "animatic":
        s.transition(project_id, ProjectState.ANIMATIC_APPROVED)
    elif stage == "videos":
        s.transition(project_id, ProjectState.VIDEOS_APPROVED)
    else:
        raise typer.BadParameter(
            "stage must be structure, narration, voice, shot_skeleton, master_footage, "
            "editorial_shots, images, animatic, or videos"
        )
    console.print(f"[green]Approved {stage}[/green]")


@app.command("prepare-images")
def prepare_images(project_id: str, workspace: Path = Path("projects")) -> None:
    s = store(workspace)
    manifest = prepare_media_jobs(s.project_dir(project_id), "image")
    s.transition(project_id, ProjectState.IMAGES_GENERATING)
    console.print_json(data=manifest.model_dump(mode="json"))


@app.command("generate-images")
def generate_images(
    project_id: str,
    asset_ids: str = typer.Option("", help="Comma-separated asset or linked shot IDs"),
    force: bool = typer.Option(False),
    workspace: Path = Path("projects"),
) -> None:
    s = store(workspace)
    manifest = generate_media_jobs(
        s.project_dir(project_id), media_type="image", shot_ids=_csv(asset_ids) or None, force=force,
    )
    transition_after_media(s, project_id, "image", manifest)
    console.print_json(data=manifest.model_dump(mode="json"))


@app.command("approve-images")
def approve_images(
    project_id: str,
    asset_ids: str = typer.Option(""),
    workspace: Path = Path("projects"),
) -> None:
    s = store(workspace)
    manifest = approve_media(
        s.project_dir(project_id), media_type="image", shot_ids=_csv(asset_ids) or None,
    )
    if all(job.status == "approved" for job in manifest.jobs):
        s.transition(project_id, ProjectState.IMAGES_APPROVED)
    console.print_json(data=manifest.model_dump(mode="json"))


@app.command("render-animatic")
def render_animatic_cmd(project_id: str, workspace: Path = Path("projects")) -> None:
    s = store(workspace)
    manifest = render_animatic(s.project_dir(project_id))
    s.transition(project_id, ProjectState.ANIMATIC_READY)
    console.print_json(data=manifest.model_dump(mode="json"))


@app.command("approve-animatic")
def approve_animatic_cmd(project_id: str, workspace: Path = Path("projects")) -> None:
    s = store(workspace)
    if not (s.project_dir(project_id) / "08_animatic/animatic.mp4").exists():
        raise typer.BadParameter("render the animatic before approval")
    s.transition(project_id, ProjectState.ANIMATIC_APPROVED)
    console.print("[green]Approved animatic[/green]")


@app.command("prepare-videos")
def prepare_videos(project_id: str, workspace: Path = Path("projects")) -> None:
    s = store(workspace)
    manifest = prepare_media_jobs(s.project_dir(project_id), "video")
    s.transition(project_id, ProjectState.VIDEOS_GENERATING)
    console.print_json(data=manifest.model_dump(mode="json"))


@app.command("generate-videos")
def generate_videos(
    project_id: str,
    asset_ids: str = typer.Option("", help="Comma-separated asset or linked shot IDs"),
    force: bool = typer.Option(False),
    workspace: Path = Path("projects"),
) -> None:
    s = store(workspace)
    if s.manifest(project_id).state not in {
        ProjectState.ANIMATIC_APPROVED, ProjectState.VIDEOS_GENERATING, ProjectState.VIDEOS_REVIEW,
    }:
        raise typer.BadParameter("approve the image-and-sound animatic before video generation")
    manifest = generate_media_jobs(
        s.project_dir(project_id), media_type="video", shot_ids=_csv(asset_ids) or None, force=force,
    )
    transition_after_media(s, project_id, "video", manifest)
    console.print_json(data=manifest.model_dump(mode="json"))


@app.command("recover-video-local")
def recover_video_local(
    project_id: str,
    asset_id: str,
    force: bool = typer.Option(False),
    workspace: Path = Path("projects"),
) -> None:
    """Create a review-only local motion fallback without any provider call."""
    s = store(workspace)
    manifest = recover_video_with_local_motion(
        s.project_dir(project_id), asset_id, force=force,
    )
    transition_after_media(s, project_id, "video", manifest)
    console.print("[yellow]Local fallback created with no generation-provider call; manual review is required.[/yellow]")
    console.print_json(data=manifest.model_dump(mode="json"))


@app.command("approve-videos")
def approve_videos(
    project_id: str,
    asset_ids: str = typer.Option(""),
    workspace: Path = Path("projects"),
) -> None:
    s = store(workspace)
    manifest = approve_media(
        s.project_dir(project_id), media_type="video", shot_ids=_csv(asset_ids) or None,
    )
    if all(job.status in {"approved", "rejected"} for job in manifest.jobs):
        s.transition(project_id, ProjectState.VIDEOS_APPROVED)
    console.print_json(data=manifest.model_dump(mode="json"))


@app.command("render-final-preview")
def render_final_preview_cmd(project_id: str, workspace: Path = Path("projects")) -> None:
    s = store(workspace)
    output = render_final_preview(s.project_dir(project_id))
    s.transition(project_id, ProjectState.FINAL_PREVIEW_READY)
    console.print(f"[green]Rendered final preview[/green] {output}")


@app.command("import-narration")
def import_narration(project_id: str, audio: Path, workspace: Path = Path("projects")) -> None:
    s = store(workspace)
    project = s.project_dir(project_id)
    destination = project / "04_voice/voiceover_master.wav"
    safe_copy(audio, destination)
    write_json(
        project / "04_voice/manual_import.json",
        {"source": str(audio), "destination": str(destination.relative_to(project))},
    )
    s.transition(project_id, ProjectState.VOICE_REVIEW)
    console.print("[green]Manual voiceover imported[/green]")


@app.command("run")
def run_pipeline(
    project_id: str,
    agent: str = "manual",
    consume_response: bool = False,
    workspace: Path = Path("projects"),
) -> None:
    """Advance until the next manual approval or media-spend gate."""
    s = store(workspace)
    while True:
        state = s.manifest(project_id).state
        if state == ProjectState.PROJECT_CREATED:
            _run_agent(lambda: generate_research(s, project_id, agent, consume_response))
        elif state == ProjectState.RESEARCH_READY:
            _run_agent(lambda: generate_structure(s, project_id, agent, consume_response))
        elif state == ProjectState.STRUCTURE_APPROVED:
            _run_agent(lambda: generate_script(s, project_id, agent, consume_response))
        elif state == ProjectState.NARRATION_APPROVED:
            generate_voice_stage(s, project_id, provider=os.getenv("FDE_VOICE_PROVIDER", "gemini"))
        elif state == ProjectState.VOICE_APPROVED:
            if not (s.project_dir(project_id) / "05_timing/audio_timing.json").exists():
                generate_timing_stage(s, project_id)
            generate_shot_skeleton_stage(s, project_id)
        elif state == ProjectState.SHOT_SKELETON_APPROVED:
            generate_master_footage_stage(s, project_id, agent, consume_response)
        elif state == ProjectState.MASTER_PLAN_APPROVED:
            generate_editorial_shots_stage(s, project_id, agent, consume_response)
        elif state == ProjectState.SHOTS_APPROVED:
            prepare_media_jobs(s.project_dir(project_id), "image")
            s.transition(project_id, ProjectState.IMAGES_GENERATING)
            console.print("[yellow]Stopped: generate and approve the 24 package images.[/yellow]")
            return
        elif state == ProjectState.IMAGES_APPROVED:
            render_animatic(s.project_dir(project_id))
            s.transition(project_id, ProjectState.ANIMATIC_READY)
            console.print("[yellow]Stopped: review and approve the editorial animatic.[/yellow]")
            return
        elif state == ProjectState.ANIMATIC_APPROVED:
            prepare_media_jobs(s.project_dir(project_id), "video")
            s.transition(project_id, ProjectState.VIDEOS_GENERATING)
            console.print("[yellow]Stopped: generate the 24 package videos.[/yellow]")
            return
        elif state == ProjectState.VIDEOS_APPROVED:
            output = render_final_preview(s.project_dir(project_id))
            s.transition(project_id, ProjectState.FINAL_PREVIEW_READY)
            console.print(f"[green]Final preview ready[/green] {output}")
            return
        else:
            console.print(f"[yellow]Stopped for review: {state.value}.[/yellow]")
            return


@app.command()
def status(project_id: str, workspace: Path = Path("projects")) -> None:
    s = store(workspace)
    console.print_json(data=s.manifest(project_id).model_dump(mode="json"))
    for relative in (
        "04_voice/audio_manifest.json", "05_timing/audio_timing.json",
        "06_shots/shot_skeleton.json", "05_master_assets/master_footage_plan.json",
        "05_master_assets/approved_master_footage_plan.json",
        "06_shots/editorial_shot_plan.json", "07_images/jobs.json", "09_videos/jobs.json",
        "12_timeline/timeline.json",
    ):
        path = s.project_dir(project_id) / relative
        if path.exists():
            console.print_json(data=read_json(path))


@app.command()
def studio(
    host: str = "127.0.0.1", port: int = 8765, workspace: Path = Path("projects"),
    project_id: str | None = None,
) -> None:
    import uvicorn
    from .studio.server import create_app
    query = f"?project={project_id}#production" if project_id else "#dashboard"
    console.print(f"Open http://{host}:{port}/{query}")
    uvicorn.run(create_app(workspace), host=host, port=port)


if __name__ == "__main__":
    app()
