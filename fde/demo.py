from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .assets import generate_image_prompts
from .contact_sheet import generate_contact_sheet
from .io import write_json
from .models import ProjectBrief, ProjectState, ReviewStatus
from .optimizer import optimize_shots
from .pipeline import generate_research, generate_script, generate_shots, generate_structure
from .project import ProjectStore


def create_demo(store: ProjectStore, project_id: str) -> Path:
    brief = ProjectBrief(
        project_id=project_id,
        title="MH370 Demo Investigation",
        topic="Demonstration project for a missing-aircraft investigation documentary",
        target_duration_seconds=480,
        maximum_master_assets=28,
    )
    project_dir = store.create(brief)
    generate_research(store, project_id, "mock")
    generate_structure(store, project_id, "mock")
    store.approve_version(project_id, "structure")
    store.transition(project_id, ProjectState.STRUCTURE_APPROVED)
    generate_script(store, project_id, "mock")
    store.approve_version(project_id, "script")
    store.transition(project_id, ProjectState.SCRIPT_APPROVED)
    generate_shots(store, project_id, "mock")
    from .io import load_model
    from .models import ShotPlan
    shot_plan = load_model(project_dir / "04_shot_plan/shot_plan.json", ShotPlan)
    plan = optimize_shots(shot_plan, brief.maximum_master_assets)
    plan = generate_image_prompts(plan, shot_plan)
    images = project_dir / "08_generated_images/approved"
    images.mkdir(parents=True, exist_ok=True)
    for index, asset in enumerate(plan.assets):
        path = images / f"{asset.asset_id}_v01.png"
        _demo_image(path, asset.asset_id, asset.title, index)
        asset.image_version = 1
        asset.approved_image = str(path.relative_to(project_dir))
        asset.image_review.status = ReviewStatus.PENDING
    write_json(project_dir / "05_master_assets/master_assets.json", plan)
    store.transition(project_id, ProjectState.IMAGE_REVIEW)
    generate_contact_sheet(project_dir)
    return project_dir


def _demo_image(path: Path, asset_id: str, title: str, index: int) -> None:
    width, height = 1600, 900
    image = Image.new("RGB", (width, height), (8 + index * 3 % 20, 28 + index * 5 % 40, 41 + index * 7 % 50))
    draw = ImageDraw.Draw(image)
    for r in range(700, 50, -70):
        draw.ellipse((width//2-r, height//2-r, width//2+r, height//2+r), outline=(30, 90, 105), width=3)
    draw.line((0, height*0.65, width, height*0.35), fill=(203, 133, 64), width=8)
    try:
        big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 110)
        small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 48)
    except Exception:
        big = small = ImageFont.load_default()
    draw.text((90, 90), asset_id, font=big, fill=(239, 246, 248))
    draw.text((90, 250), title[:58], font=small, fill=(218, 225, 225))
    image.save(path)
