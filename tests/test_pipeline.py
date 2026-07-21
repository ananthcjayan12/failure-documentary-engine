from pathlib import Path

from fde.assets import generate_image_prompts
from fde.contact_sheet import generate_contact_sheet
from fde.demo import create_demo
from fde.io import load_model, write_json
from fde.models import MasterAssetPlan, ProjectBrief, ReviewStatus, Shot, ShotPlan
from fde.optimizer import optimize_shots
from fde.project import ProjectStore
from fde.review import review_asset
from fde.timeline import build_timeline


def test_project_init(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    brief = ProjectBrief(project_id="test", title="Test", topic="Test")
    project = store.create(brief)
    assert (project / "00_input/project_brief.json").exists()
    assert store.manifest("test").state.value == "PROJECT_CREATED"


def test_optimizer_hard_limit_and_coverage():
    shots = [
        Shot(
            shot_id=f"S{i:03d}", chapter_id=f"CH{i%5:02d}", narration_ids=[f"N{i:03d}"],
            start=float(i * 5), duration=5, visual_purpose="Explain evidence",
            visual_type=["map", "radar", "ocean", "cockpit"][i % 4],
            suggested_visual=f"Reusable visual {i % 4}", camera="wide", motion="subtle",
        ) for i in range(50)
    ]
    plan = optimize_shots(ShotPlan(project_id="x", shots=shots, total_seconds=250), 28)
    assert len(plan.assets) <= 28
    assert not plan.uncovered_shots
    assert sum(len(a.linked_shots) for a in plan.assets) == 50


def test_contact_sheet_generated(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    project = create_demo(store, "demo")
    outputs = generate_contact_sheet(project, width=1600, height=2400)
    assert Path(outputs["png"]).exists()
    assert Path(outputs["pdf"]).exists()
    assert Path(outputs["html"]).exists()


def test_asset_change_invalidation_is_local(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    project = create_demo(store, "demo")
    plan = load_model(project / "05_master_assets/master_assets.json", MasterAssetPlan)
    target = plan.assets[0]
    other = plan.assets[1]
    review_asset(store, "demo", target.asset_id, ReviewStatus.CHANGE_REQUESTED, "Change framing")
    manifest = store.manifest("demo")
    assert f"asset:{target.asset_id}:image" in manifest.invalidated_targets
    assert f"asset:{other.asset_id}:image" not in manifest.invalidated_targets


def test_timeline_has_every_shot(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    project = create_demo(store, "demo")
    timeline = build_timeline(project)
    from fde.models import ShotPlan
    shot_plan = load_model(project / "04_shot_plan/shot_plan.json", ShotPlan)
    assert len(timeline.entries) == len(shot_plan.shots)
    assert {e.shot_id for e in timeline.entries} == {s.shot_id for s in shot_plan.shots}


def test_image_factory_packet_export(tmp_path: Path):
    from fde.image_factory import export_image_factory_packet

    store = ProjectStore(tmp_path / "projects")
    project = create_demo(store, "factory-demo")
    result = export_image_factory_packet(project)
    packet = Path(result["packet_directory"])
    archive = Path(result["packet_zip"])
    assert archive.exists()
    assert (packet / "ASSET_MANIFEST.json").exists()
    manifest = __import__("json").loads((packet / "ASSET_MANIFEST.json").read_text())
    plan = load_model(project / "05_master_assets/master_assets.json", MasterAssetPlan)
    assert len(manifest["assets"]) == len(plan.assets)
    assert len(manifest["batches"]) >= 1
    assert all(item["expected_filename"].startswith(item["asset_id"]) for item in manifest["assets"])


def test_image_factory_batch_import_normalizes_ratio(tmp_path: Path):
    import zipfile
    from PIL import Image
    from fde.image_factory import import_image_factory_batch

    store = ProjectStore(tmp_path / "projects")
    project = create_demo(store, "factory-import")
    plan = load_model(project / "05_master_assets/master_assets.json", MasterAssetPlan)
    asset_id = plan.assets[0].asset_id
    source_dir = tmp_path / "returned"
    source_dir.mkdir()
    # ChatGPT landscape images may be 3:2 rather than exact 16:9.
    Image.new("RGB", (1536, 1024), "navy").save(source_dir / f"{asset_id}_returned.png")
    archive_path = tmp_path / "returned.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.write(source_dir / f"{asset_id}_returned.png", f"images/{asset_id}_returned.png")
    report = import_image_factory_batch(project, archive_path)
    assert report["validation"]["imported"]
    updated = load_model(project / "05_master_assets/master_assets.json", MasterAssetPlan)
    imported = next(item for item in updated.assets if item.asset_id == asset_id)
    with Image.open(project / imported.approved_image) as image:
        assert image.size == (1600, 900)
