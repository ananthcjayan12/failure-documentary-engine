from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from .agents import AgentPending
from .assets import generate_image_prompts, import_images
from .contact_sheet import generate_contact_sheet
from .demo import create_demo
from .io import load_model, read_json, safe_copy, write_json
from .image_factory import export_image_factory_packet, import_image_factory_batch
from .media import create_variants, has_command, import_videos
from .providers.media_factory import generate_project_media
from .models import (
    MasterAssetPlan,
    ProjectBrief,
    ProjectState,
    ReviewStatus,
    ShotPlan,
)
from .optimizer import optimize_shots
from .pipeline import generate_research, generate_script, generate_shots, generate_structure
from .project import ProjectStore
from .render import render
from .review import approval_summary, review_asset
from .timeline import build_timeline
from .video_jobs import create_video_jobs

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

app = typer.Typer(help="Failure Documentary Engine")
console = Console()


def store(workspace: Path) -> ProjectStore:
    return ProjectStore(workspace)


def _run_agent(callable_):
    try:
        result = callable_()
        console.print(f"[green]Created {type(result).__name__}[/green]")
    except AgentPending as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        raise typer.Exit(code=2)


@app.command()
def doctor() -> None:
    """Check local dependencies."""
    table = Table("Tool", "Available", "Purpose")
    for name, purpose in [("ffmpeg", "rendering and variants"), ("ffprobe", "video validation"), ("codex", "optional command agent"), ("grok", "Grok reasoning and Imagine media"), ("npx", "local HyperFrames runtime")]:
        table.add_row(name, "yes" if has_command(name) else "no", purpose)
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
        project_id=project_id, title=title, topic=topic or title,
        target_duration_seconds=duration, maximum_master_assets=max_assets,
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


@app.command()
def script(project_id: str, agent: str = "manual", consume_response: bool = False, workspace: Path = Path("projects")) -> None:
    _run_agent(lambda: generate_script(store(workspace), project_id, agent, consume_response))


@app.command()
def shots(project_id: str, agent: str = "manual", consume_response: bool = False, workspace: Path = Path("projects")) -> None:
    _run_agent(lambda: generate_shots(store(workspace), project_id, agent, consume_response))


@app.command("approve-stage")
def approve_stage(project_id: str, stage: str, workspace: Path = Path("projects")) -> None:
    mapping = {
        "structure": ProjectState.STRUCTURE_APPROVED,
        "script": ProjectState.SCRIPT_APPROVED,
    }
    if stage not in mapping:
        raise typer.BadParameter("stage must be structure or script")
    s = store(workspace)
    s.approve_version(project_id, stage)
    s.transition(project_id, mapping[stage])
    console.print(f"[green]Approved {stage}[/green]")


@app.command("optimize-assets")
def optimize_assets(project_id: str, max_assets: int | None = None, workspace: Path = Path("projects")) -> None:
    s = store(workspace)
    brief = s.brief(project_id)
    shot_plan = load_model(s.project_dir(project_id) / "04_shot_plan/shot_plan.json", ShotPlan)
    plan = optimize_shots(shot_plan, max_assets or brief.maximum_master_assets)
    write_json(s.project_dir(project_id) / "05_master_assets/master_assets.json", plan)
    reuse = {asset.asset_id: asset.linked_shots for asset in plan.assets}
    write_json(s.project_dir(project_id) / "05_master_assets/reuse_matrix.json", reuse)
    coverage = {
        "shot_count": len(shot_plan.shots), "asset_count": len(plan.assets),
        "maximum": plan.maximum_assets, "uncovered_shots": plan.uncovered_shots,
    }
    write_json(s.project_dir(project_id) / "05_master_assets/coverage_report.json", coverage)
    s.transition(project_id, ProjectState.ASSET_PLAN_READY)
    console.print(f"[green]Compressed {len(shot_plan.shots)} shots into {len(plan.assets)} assets[/green]")


@app.command("generate-image-prompts")
def image_prompts(project_id: str, workspace: Path = Path("projects")) -> None:
    s = store(workspace)
    plan_path = s.project_dir(project_id) / "05_master_assets/master_assets.json"
    plan = load_model(plan_path, MasterAssetPlan)
    shot_plan = load_model(s.project_dir(project_id) / "04_shot_plan/shot_plan.json", ShotPlan)
    plan = generate_image_prompts(plan, shot_plan)
    write_json(plan_path, plan)
    for asset in plan.assets:
        (s.project_dir(project_id) / f"05_master_assets/prompts/{asset.asset_id}.txt").write_text(asset.image_prompt + "\n", encoding="utf-8")
    s.transition(project_id, ProjectState.IMAGE_GENERATION)
    console.print(f"[green]Generated {len(plan.assets)} image prompts[/green]")


@app.command("generate-media")
def generate_media_cmd(
    project_id: str,
    media_type: str = typer.Argument(..., help="image or video"),
    asset_ids: str = typer.Option("", help="Comma-separated asset IDs; blank generates every pending asset"),
    force: bool = typer.Option(False, help="Regenerate even when a candidate already exists"),
    workspace: Path = Path("projects"),
) -> None:
    """Generate image or video assets through the routed native/manual/custom provider."""
    if media_type not in {"image", "video"}:
        raise typer.BadParameter("media_type must be image or video")
    s = store(workspace)
    project = s.project_dir(project_id)
    brief = s.brief(project_id)
    if media_type == "video" and not (project / "09_video_jobs/video_jobs.json").exists():
        create_video_jobs(project, brief.master_video_duration_seconds)
    os.environ["FDE_MEDIA_DURATION"] = str(brief.master_video_duration_seconds)
    route = {
        "provider": os.environ.get("FDE_MEDIA_PROVIDER", "mock"),
        "model": os.environ.get("FDE_MEDIA_MODEL", "Deterministic Demo"),
        "timeout_seconds": int(float(os.environ.get("FDE_MEDIA_TIMEOUT", "3600") or 3600)),
        "retry_count": int(float(os.environ.get("FDE_MEDIA_RETRIES", "0") or 0)),
        "media_command_template": os.environ.get("FDE_MEDIA_COMMAND", ""),
        "fallback_provider": os.environ.get("FDE_MEDIA_FALLBACK_PROVIDER", ""),
        "fallback_model": os.environ.get("FDE_MEDIA_FALLBACK_MODEL", ""),
        "fallback_media_command_template": os.environ.get("FDE_MEDIA_FALLBACK_COMMAND", ""),
    }
    report = generate_project_media(
        project, media_type=media_type, route=route,
        asset_ids=[item.strip().upper() for item in asset_ids.split(",") if item.strip()],
        force=force,
    )
    if report.get("generated"):
        s.transition(project_id, ProjectState.IMAGE_REVIEW if media_type == "image" else ProjectState.VIDEO_REVIEW)
    elif report.get("manual_required"):
        s.transition(project_id, ProjectState.IMAGE_GENERATION if media_type == "image" else ProjectState.VIDEO_GENERATION)
    console.print_json(data=report)
    if report.get("failed") and not report.get("generated"):
        raise typer.Exit(code=1)


@app.command("import-images")
def import_images_cmd(project_id: str, workspace: Path = Path("projects"), min_width: int = 1280) -> None:
    s = store(workspace)
    report = import_images(s.project_dir(project_id), min_width=min_width)
    s.transition(project_id, ProjectState.IMAGE_REVIEW)
    console.print_json(data=report)


@app.command("contact-sheet")
def contact_sheet(project_id: str, workspace: Path = Path("projects")) -> None:
    paths = generate_contact_sheet(store(workspace).project_dir(project_id))
    console.print_json(data=paths)


@app.command("export-image-factory")
def export_image_factory(
    project_id: str,
    output_dir: Path | None = None,
    workspace: Path = Path("projects"),
) -> None:
    """Create the one-upload production packet for the private Custom GPT."""
    paths = export_image_factory_packet(store(workspace).project_dir(project_id), output_dir)
    console.print_json(data=paths)


@app.command("import-image-batch")
def import_image_batch(
    project_id: str,
    batch_zip: Path,
    workspace: Path = Path("projects"),
    min_width: int = 1280,
) -> None:
    """Import and normalize a ZIP returned by the Documentary Image Factory GPT."""
    s = store(workspace)
    report = import_image_factory_batch(s.project_dir(project_id), batch_zip, min_width=min_width)
    s.transition(project_id, ProjectState.IMAGE_REVIEW)
    console.print_json(data=report)


@app.command("review-asset")
def review_asset_cmd(
    project_id: str,
    asset_id: str,
    status: ReviewStatus,
    instruction: str = "",
    preserve: str = "",
    target: str = "image",
    workspace: Path = Path("projects"),
) -> None:
    review_asset(
        store(workspace), project_id, asset_id, status, instruction,
        [x.strip() for x in preserve.split(",") if x.strip()], target,
    )
    console.print(f"[green]Saved {target} review for {asset_id}[/green]")


@app.command("regenerate-asset")
def regenerate_asset(project_id: str, asset_id: str, workspace: Path = Path("projects")) -> None:
    s = store(workspace)
    path = s.project_dir(project_id) / "05_master_assets/master_assets.json"
    plan = load_model(path, MasterAssetPlan)
    asset = next((a for a in plan.assets if a.asset_id == asset_id), None)
    if not asset:
        raise typer.BadParameter(f"unknown asset {asset_id}")
    instruction = asset.image_review.instruction
    preserve = ", ".join(asset.image_review.preserve)
    revision = (
        asset.image_prompt + "\n\nREVISION REQUEST:\n" + instruction +
        "\nPRESERVE WITHOUT CHANGE:\n" + (preserve or "all unmentioned approved properties")
    )
    version = asset.image_version + 1
    out = s.project_dir(project_id) / f"05_master_assets/prompts/{asset_id}_revision_v{version:02d}.txt"
    out.write_text(revision + "\n", encoding="utf-8")
    console.print(f"[green]Created revision prompt[/green] {out}")


@app.command("validate-assets")
def validate_assets(project_id: str, workspace: Path = Path("projects")) -> None:
    s = store(workspace)
    summary = approval_summary(s.project_dir(project_id))
    console.print_json(data=summary)
    if summary["missing_images"] or summary["pending_image_reviews"] or summary["uncovered_shots"]:
        raise typer.Exit(code=1)
    project = s.project_dir(project_id)
    paths = generate_contact_sheet(project)
    plan = load_model(project / "05_master_assets/master_assets.json", MasterAssetPlan)
    write_json(project / "07_review/approved_asset_manifest_v01.json", plan)
    safe_copy(Path(paths["png"]), project / "07_review/approved_contact_sheet_v01.png")
    s.transition(project_id, ProjectState.IMAGES_APPROVED)


@app.command("video-jobs")
def video_jobs(project_id: str, workspace: Path = Path("projects")) -> None:
    s = store(workspace)
    brief = s.brief(project_id)
    manifest = create_video_jobs(s.project_dir(project_id), brief.master_video_duration_seconds)
    s.transition(project_id, ProjectState.VIDEO_GENERATION)
    console.print(f"[green]Created {len(manifest.jobs)} video jobs[/green]")


@app.command("import-videos")
def import_videos_cmd(project_id: str, workspace: Path = Path("projects")) -> None:
    s = store(workspace)
    brief = s.brief(project_id)
    report = import_videos(s.project_dir(project_id), brief.master_video_duration_seconds)
    s.transition(project_id, ProjectState.VIDEO_REVIEW)
    console.print_json(data=report)


@app.command("validate-videos")
def validate_videos(project_id: str, workspace: Path = Path("projects")) -> None:
    s = store(workspace)
    summary = approval_summary(s.project_dir(project_id))
    console.print_json(data=summary)
    if summary["missing_videos"] or summary["pending_video_reviews"]:
        raise typer.Exit(code=1)
    s.transition(project_id, ProjectState.VIDEOS_APPROVED)


@app.command("create-variants")
def variants(project_id: str, workspace: Path = Path("projects")) -> None:
    manifest = create_variants(store(workspace).project_dir(project_id))
    console.print(f"[green]Created variants for {len(manifest['assets'])} assets[/green]")


@app.command("import-narration")
def import_narration(
    project_id: str, audio: Path, timestamps: Path | None = None,
    workspace: Path = Path("projects"),
) -> None:
    s = store(workspace)
    project = s.project_dir(project_id)
    suffix = audio.suffix.lower() or ".wav"
    safe_copy(audio, project / f"11_narration/narration_master{suffix}")
    if timestamps:
        write_json(project / "11_narration/word_timestamps.json", read_json(timestamps))
    s.transition(project_id, ProjectState.NARRATION_READY)
    console.print("[green]Narration imported[/green]")


@app.command("build-timeline")
def build_timeline_cmd(project_id: str, workspace: Path = Path("projects")) -> None:
    timeline = build_timeline(store(workspace).project_dir(project_id))
    console.print(f"[green]Timeline: {len(timeline.entries)} entries, {timeline.total_seconds:.1f}s[/green]")


@app.command("render-preview")
def render_preview(project_id: str, workspace: Path = Path("projects")) -> None:
    s = store(workspace)
    out = render(s.project_dir(project_id), preview=True, width=1280, height=720)
    s.transition(project_id, ProjectState.PREVIEW_REVIEW)
    console.print(f"[green]Rendered[/green] {out}")


@app.command("render-final-base")
def render_final(project_id: str, workspace: Path = Path("projects")) -> None:
    s = store(workspace)
    out = render(s.project_dir(project_id), preview=False, width=1920, height=1080)
    s.transition(project_id, ProjectState.PICTURE_LOCKED)
    console.print(f"[green]Rendered[/green] {out}")


@app.command("run")
def run_pipeline(
    project_id: str,
    agent: str = "manual",
    consume_response: bool = False,
    workspace: Path = Path("projects"),
) -> None:
    """Advance all automatic stages until the next human review gate."""
    s = store(workspace)
    while True:
        state = s.manifest(project_id).state
        if state == ProjectState.PROJECT_CREATED:
            _run_agent(lambda: generate_research(s, project_id, agent, consume_response))
        elif state == ProjectState.RESEARCH_READY:
            _run_agent(lambda: generate_structure(s, project_id, agent, consume_response))
        elif state == ProjectState.STRUCTURE_REVIEW:
            console.print("[yellow]Stopped: approve the structure with `fde approve-stage PROJECT structure`.[/yellow]")
            return
        elif state == ProjectState.STRUCTURE_APPROVED:
            _run_agent(lambda: generate_script(s, project_id, agent, consume_response))
        elif state == ProjectState.SCRIPT_REVIEW:
            console.print("[yellow]Stopped: approve the script with `fde approve-stage PROJECT script`.[/yellow]")
            return
        elif state == ProjectState.SCRIPT_APPROVED:
            _run_agent(lambda: generate_shots(s, project_id, agent, consume_response))
        elif state == ProjectState.SHOT_PLAN_READY:
            brief = s.brief(project_id)
            shot_plan = load_model(s.project_dir(project_id) / "04_shot_plan/shot_plan.json", ShotPlan)
            plan = optimize_shots(shot_plan, brief.maximum_master_assets)
            write_json(s.project_dir(project_id) / "05_master_assets/master_assets.json", plan)
            s.transition(project_id, ProjectState.ASSET_PLAN_READY)
        elif state == ProjectState.ASSET_PLAN_READY:
            plan_path = s.project_dir(project_id) / "05_master_assets/master_assets.json"
            plan = load_model(plan_path, MasterAssetPlan)
            shot_plan = load_model(s.project_dir(project_id) / "04_shot_plan/shot_plan.json", ShotPlan)
            plan = generate_image_prompts(plan, shot_plan)
            write_json(plan_path, plan)
            for asset in plan.assets:
                (s.project_dir(project_id) / f"05_master_assets/prompts/{asset.asset_id}.txt").write_text(asset.image_prompt + "\n", encoding="utf-8")
            s.transition(project_id, ProjectState.IMAGE_GENERATION)
        elif state == ProjectState.IMAGE_GENERATION:
            console.print("[yellow]Stopped: generate images, place them in the image inbox, and run `fde import-images`.[/yellow]")
            return
        elif state == ProjectState.IMAGE_REVIEW:
            console.print("[yellow]Stopped: review and approve all images, then run `fde validate-assets`.[/yellow]")
            return
        elif state == ProjectState.IMAGES_APPROVED:
            brief = s.brief(project_id)
            create_video_jobs(s.project_dir(project_id), brief.master_video_duration_seconds)
            s.transition(project_id, ProjectState.VIDEO_GENERATION)
        elif state == ProjectState.VIDEO_GENERATION:
            console.print("[yellow]Stopped: generate Grok videos, place them in the video inbox, and run `fde import-videos`.[/yellow]")
            return
        elif state == ProjectState.VIDEO_REVIEW:
            console.print("[yellow]Stopped: review all videos, then run `fde validate-videos`.[/yellow]")
            return
        elif state == ProjectState.VIDEOS_APPROVED:
            create_variants(s.project_dir(project_id))
            console.print("[yellow]Variants are ready. Import narration and build the timeline.[/yellow]")
            return
        else:
            console.print(f"[yellow]No automatic transition configured from {state.value}.[/yellow]")
            return


@app.command()
def status(project_id: str, workspace: Path = Path("projects")) -> None:
    s = store(workspace)
    manifest = s.manifest(project_id)
    console.print_json(data=manifest.model_dump(mode="json"))
    plan_path = s.project_dir(project_id) / "05_master_assets/master_assets.json"
    if plan_path.exists():
        console.print_json(data=approval_summary(s.project_dir(project_id)))


@app.command()
def studio(
    host: str = "127.0.0.1",
    port: int = 8765,
    workspace: Path = Path("projects"),
    project_id: str | None = None,
) -> None:
    """Launch the modern local production studio."""
    import uvicorn
    from .studio.server import create_app
    query = f"?project={project_id}#production" if project_id else "#dashboard"
    console.print(f"Open http://{host}:{port}/{query}")
    uvicorn.run(create_app(workspace), host=host, port=port)


@app.command()
def review(project_id: str, host: str = "127.0.0.1", port: int = 8765, workspace: Path = Path("projects")) -> None:
    """Launch Studio directly in the asset-review workspace."""
    import uvicorn
    from .studio.server import create_app
    console.print(f"Open http://{host}:{port}/?project={project_id}#assets")
    uvicorn.run(create_app(workspace), host=host, port=port)


if __name__ == "__main__":
    app()
