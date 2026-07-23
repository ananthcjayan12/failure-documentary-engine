from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from .agents import AgentPending
from .demo import create_demo
from .io import load_model, read_json, safe_copy, write_json
from .media import has_command
from .models import ProjectBrief, ProjectState, V1MediaManifest
from .pipeline import (
    generate_research,
    generate_script,
    generate_shots,
    generate_structure,
    generate_timing_stage,
    generate_voice_stage,
    generate_master_assets,
)
from .project import ProjectStore
from .v1_media import (
    approve_media,
    generate_media_jobs,
    prepare_media_jobs,
    render_animatic,
    render_final_preview,
    transition_after_media,
)

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
app = typer.Typer(help="Failure Documentary Engine — V1 audio-first production")
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
        ("ffmpeg", "voice assembly, animatic and final preview"),
        ("ffprobe", "final stream validation"),
        ("codex", "optional structured narration/research agent"),
        ("grok", "optional image and video generation"),
    ]:
        table.add_row(name, "yes" if has_command(name) else "no", purpose)
    try:
        import google.genai  # noqa: F401
        gemini = "yes"
    except Exception:
        gemini = "no"
    table.add_row("google-genai", gemini, "Gemini TTS")
    console.print(table)


@app.command()
def init(
    project_id: str,
    title: Annotated[str, typer.Option()] = "Untitled Failure Investigation",
    topic: Annotated[str, typer.Option()] = "",
    duration: Annotated[float, typer.Option()] = 480,
    max_assets: Annotated[int, typer.Option()] = 28,
    workspace: Annotated[Path, typer.Option()] = Path("projects"),
) -> None:
    brief = ProjectBrief(
        project_id=project_id,
        title=title,
        topic=topic or title,
        target_duration_seconds=duration,
        maximum_master_assets=max_assets,
    )
    path = store(workspace).create(brief)
    console.print(f"[green]Created project[/green] {path}")


@app.command()
def demo(project_id: Annotated[str, typer.Argument()] = "mh370-demo", workspace: Path = Path("projects")) -> None:
    path = create_demo(store(workspace), project_id)
    console.print(f"[green]Demo created[/green] {path}")


@app.command()
def research(project_id: str, agent: str = "manual", consume_response: bool = False, workspace: Path = Path("projects")) -> None:
    _run_agent(lambda: generate_research(store(workspace), project_id, agent, consume_response))


@app.command()
def structure(project_id: str, agent: str = "manual", consume_response: bool = False, workspace: Path = Path("projects")) -> None:
    _run_agent(lambda: generate_structure(store(workspace), project_id, agent, consume_response))


@app.command("narration")
def narration_cmd(project_id: str, agent: str = "manual", consume_response: bool = False, workspace: Path = Path("projects")) -> None:
    _run_agent(lambda: generate_script(store(workspace), project_id, agent, consume_response))


@app.command()
def script(project_id: str, agent: str = "manual", consume_response: bool = False, workspace: Path = Path("projects")) -> None:
    """Compatibility alias for `narration`."""
    narration_cmd(project_id, agent, consume_response, workspace)


@app.command("approve-stage")
def approve_stage(project_id: str, stage: str, workspace: Path = Path("projects")) -> None:
    s = store(workspace)
    mapping = {
        "structure": ("structure", ProjectState.STRUCTURE_APPROVED),
        "narration": ("narration", ProjectState.NARRATION_APPROVED),
        "script": ("narration", ProjectState.NARRATION_APPROVED),
        "voice": ("voice", ProjectState.VOICE_APPROVED),
        "shots": ("shots", ProjectState.SHOTS_APPROVED),
        "images": ("images", ProjectState.IMAGES_APPROVED),
        "animatic": ("animatic", ProjectState.ANIMATIC_APPROVED),
        "videos": ("videos", ProjectState.VIDEOS_APPROVED),
    }
    if stage not in mapping:
        raise typer.BadParameter("stage must be structure, narration, voice, shots, images, animatic, or videos")
    artifact, state = mapping[stage]
    if stage in {"structure", "narration", "script", "shots"}:
        s.approve_version(project_id, artifact)
    if stage == "shots":
        generate_master_assets(s, project_id)
    s.transition(project_id, state)
    console.print(f"[green]Approved {stage}[/green]")


@app.command("generate-voice")
def generate_voice_cmd(
    project_id: str,
    provider: str = typer.Option("gemini", help="gemini, elevenlabs, or mock"),
    model: str = typer.Option(""),
    voice: str = typer.Option(""),
    paragraphs: str = typer.Option("", help="Comma-separated paragraph IDs; blank processes all"),
    force: bool = typer.Option(False),
    workspace: Path = Path("projects"),
) -> None:
    manifest = generate_voice_stage(
        store(workspace), project_id, provider=provider, model=model or None, voice=voice or None,
        paragraph_ids=_csv(paragraphs) or None, force=force,
    )
    console.print_json(data=manifest.model_dump(mode="json"))


@app.command("generate-timing")
def generate_timing_cmd(
    project_id: str,
    allow_approximate: bool = typer.Option(False, help="Permit proportional fallback when Whisper is unavailable"),
    workspace: Path = Path("projects"),
) -> None:
    timing = generate_timing_stage(store(workspace), project_id, allow_approximate=allow_approximate)
    console.print_json(data=timing.model_dump(mode="json"))


@app.command()
def shots(project_id: str, agent: str = "deterministic", consume_response: bool = False, workspace: Path = Path("projects")) -> None:
    _run_agent(lambda: generate_shots(store(workspace), project_id, agent, consume_response))


@app.command("prepare-images")
def prepare_images(project_id: str, workspace: Path = Path("projects")) -> None:
    s = store(workspace)
    manifest = prepare_media_jobs(s.project_dir(project_id), "image")
    s.transition(project_id, ProjectState.IMAGES_GENERATING)
    console.print_json(data=manifest.model_dump(mode="json"))


@app.command("generate-images")
def generate_images(
    project_id: str,
    shot_ids: str = typer.Option(""),
    force: bool = typer.Option(False),
    workspace: Path = Path("projects"),
) -> None:
    s = store(workspace)
    manifest = generate_media_jobs(s.project_dir(project_id), media_type="image", shot_ids=_csv(shot_ids) or None, force=force)
    transition_after_media(s, project_id, "image", manifest)
    console.print_json(data=manifest.model_dump(mode="json"))


@app.command("approve-images")
def approve_images(project_id: str, shot_ids: str = typer.Option(""), workspace: Path = Path("projects")) -> None:
    s = store(workspace)
    manifest = approve_media(s.project_dir(project_id), media_type="image", shot_ids=_csv(shot_ids) or None)
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
    shot_ids: str = typer.Option(""),
    force: bool = typer.Option(False),
    workspace: Path = Path("projects"),
) -> None:
    s = store(workspace)
    if s.manifest(project_id).state not in {ProjectState.ANIMATIC_APPROVED, ProjectState.VIDEOS_GENERATING, ProjectState.VIDEOS_REVIEW}:
        raise typer.BadParameter("approve the image-and-sound animatic before video generation")
    manifest = generate_media_jobs(s.project_dir(project_id), media_type="video", shot_ids=_csv(shot_ids) or None, force=force)
    transition_after_media(s, project_id, "video", manifest)
    console.print_json(data=manifest.model_dump(mode="json"))


@app.command("approve-videos")
def approve_videos(project_id: str, shot_ids: str = typer.Option(""), workspace: Path = Path("projects")) -> None:
    s = store(workspace)
    manifest = approve_media(s.project_dir(project_id), media_type="video", shot_ids=_csv(shot_ids) or None)
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
def import_narration(
    project_id: str,
    audio: Path,
    workspace: Path = Path("projects"),
) -> None:
    """Manual fallback: import a complete WAV as the approved V1 voiceover."""
    s = store(workspace)
    project = s.project_dir(project_id)
    destination = project / "04_voice/voiceover_master.wav"
    safe_copy(audio, destination)
    write_json(project / "04_voice/manual_import.json", {"source": str(audio), "destination": str(destination.relative_to(project))})
    s.transition(project_id, ProjectState.VOICE_REVIEW)
    console.print("[green]Manual voiceover imported[/green]")


# Compatibility command names retained while existing operator scripts migrate to V1.
@app.command("generate-media")
def generate_media_compat(
    project_id: str,
    media_type: str = typer.Argument(..., help="image or video"),
    asset_ids: str = typer.Option("", help="Compatibility alias for shot IDs"),
    force: bool = typer.Option(False),
    workspace: Path = Path("projects"),
) -> None:
    if media_type == "image":
        generate_images(project_id, shot_ids=asset_ids, force=force, workspace=workspace)
    elif media_type == "video":
        generate_videos(project_id, shot_ids=asset_ids, force=force, workspace=workspace)
    else:
        raise typer.BadParameter("media_type must be image or video")


@app.command("validate-assets")
def validate_assets_compat(project_id: str, workspace: Path = Path("projects")) -> None:
    approve_images(project_id, workspace=workspace)


@app.command("video-jobs")
def video_jobs_compat(project_id: str, workspace: Path = Path("projects")) -> None:
    prepare_videos(project_id, workspace=workspace)


@app.command("validate-videos")
def validate_videos_compat(project_id: str, workspace: Path = Path("projects")) -> None:
    approve_videos(project_id, workspace=workspace)


@app.command("render-preview")
def render_preview_compat(project_id: str, workspace: Path = Path("projects")) -> None:
    render_animatic_cmd(project_id, workspace=workspace)


@app.command("render-final-base")
def render_final_compat(project_id: str, workspace: Path = Path("projects")) -> None:
    render_final_preview_cmd(project_id, workspace=workspace)


@app.command("build-timeline")
def build_timeline_compat(project_id: str, workspace: Path = Path("projects")) -> None:
    path = store(workspace).project_dir(project_id) / "06_shots/shot_plan.json"
    if not path.exists():
        raise typer.BadParameter("generate audio-led shots before building the timeline")
    console.print_json(data=read_json(path))


@app.command("create-variants")
def create_variants_compat(project_id: str, workspace: Path = Path("projects")) -> None:
    console.print("[yellow]V1 uses approved per-shot media directly; no variant stage is required.[/yellow]")


@app.command("run")
def run_pipeline(
    project_id: str,
    agent: str = "manual",
    consume_response: bool = False,
    workspace: Path = Path("projects"),
) -> None:
    """Advance automatic V1 stages until the next approval or paid-media gate."""
    s = store(workspace)
    while True:
        state = s.manifest(project_id).state
        if state == ProjectState.PROJECT_CREATED:
            _run_agent(lambda: generate_research(s, project_id, agent, consume_response))
        elif state == ProjectState.RESEARCH_READY:
            _run_agent(lambda: generate_structure(s, project_id, agent, consume_response))
        elif state == ProjectState.STRUCTURE_REVIEW:
            console.print("[yellow]Stopped: approve the structure.[/yellow]")
            return
        elif state == ProjectState.STRUCTURE_APPROVED:
            _run_agent(lambda: generate_script(s, project_id, agent, consume_response))
        elif state == ProjectState.NARRATION_REVIEW:
            console.print("[yellow]Stopped: approve the narration.[/yellow]")
            return
        elif state == ProjectState.NARRATION_APPROVED:
            provider = os.getenv("FDE_VOICE_PROVIDER", "gemini")
            generate_voice_stage(s, project_id, provider=provider)
        elif state == ProjectState.VOICE_REVIEW:
            console.print("[yellow]Stopped: review and approve the generated voice.[/yellow]")
            return
        elif state == ProjectState.VOICE_APPROVED:
            generate_timing_stage(s, project_id)
            generate_shots(s, project_id)
        elif state == ProjectState.SHOTS_REVIEW:
            console.print("[yellow]Stopped: review and approve exact shot divisions.[/yellow]")
            return
        elif state == ProjectState.SHOTS_APPROVED:
            prepare_media_jobs(s.project_dir(project_id), "image")
            s.transition(project_id, ProjectState.IMAGES_GENERATING)
            console.print("[yellow]Stopped: generate and approve shot images.[/yellow]")
            return
        elif state == ProjectState.IMAGES_APPROVED:
            render_animatic(s.project_dir(project_id))
            s.transition(project_id, ProjectState.ANIMATIC_READY)
            console.print("[yellow]Stopped: review and approve the image-and-sound animatic.[/yellow]")
            return
        elif state == ProjectState.ANIMATIC_APPROVED:
            prepare_media_jobs(s.project_dir(project_id), "video")
            s.transition(project_id, ProjectState.VIDEOS_GENERATING)
            console.print("[yellow]Stopped: generate only the approved video shots.[/yellow]")
            return
        elif state == ProjectState.VIDEOS_APPROVED:
            output = render_final_preview(s.project_dir(project_id))
            s.transition(project_id, ProjectState.FINAL_PREVIEW_READY)
            console.print(f"[green]Final preview ready[/green] {output}")
            return
        else:
            console.print(f"[yellow]No automatic transition configured from {state.value}.[/yellow]")
            return


@app.command()
def status(project_id: str, workspace: Path = Path("projects")) -> None:
    s = store(workspace)
    console.print_json(data=s.manifest(project_id).model_dump(mode="json"))
    for relative in ("04_voice/audio_manifest.json", "05_timing/audio_timing.json", "06_shots/shot_plan.json", "07_images/jobs.json", "09_videos/jobs.json"):
        path = s.project_dir(project_id) / relative
        if path.exists():
            console.print_json(data=read_json(path))


@app.command()
def studio(
    host: str = "127.0.0.1",
    port: int = 8765,
    workspace: Path = Path("projects"),
    project_id: str | None = None,
) -> None:
    import uvicorn
    from .studio.server import create_app
    query = f"?project={project_id}#production" if project_id else "#dashboard"
    console.print(f"Open http://{host}:{port}/{query}")
    uvicorn.run(create_app(workspace), host=host, port=port)


if __name__ == "__main__":
    app()
