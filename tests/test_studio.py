from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from fde.demo import create_demo
from fde.project import ProjectStore
from fde.studio.server import create_app


def test_studio_bootstrap_and_modern_routes(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    create_demo(store, "demo")
    client = TestClient(create_app(store.workspace))

    bootstrap = client.get("/api/bootstrap")
    assert bootstrap.status_code == 200
    payload = bootstrap.json()
    assert payload["projects"][0]["project_id"] == "demo"
    assert len(payload["stage_definitions"]) == 8

    project = client.get("/api/projects/demo").json()
    assert project["state"] == "IMAGE_REVIEW"
    review_stages = [stage["id"] for stage in project["stages"] if stage["status"] == "review"]
    assert review_stages == ["image_review"]
    assert project["next_action"]["id"] == "review_images"

    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_studio_project_creation_and_settings(tmp_path: Path):
    client = TestClient(create_app(tmp_path / "projects"))
    config = client.patch("/api/config", json={"agent_mode": "mock", "default_max_assets": 24})
    assert config.status_code == 200
    assert config.json()["agent_mode"] == "mock"

    response = client.post(
        "/api/projects",
        json={
            "project_id": "bridge-failure",
            "title": "The Bridge That Fell",
            "topic": "Investigate a major structural collapse",
            "target_duration_seconds": 480,
            "maximum_master_assets": 24,
        },
    )
    assert response.status_code == 201
    assert response.json()["state"] == "PROJECT_CREATED"


def test_studio_background_job_is_resumable(tmp_path: Path):
    workspace = tmp_path / "projects"
    client = TestClient(create_app(workspace))
    client.patch("/api/config", json={"agent_mode": "mock"})
    client.post(
        "/api/projects",
        json={"project_id": "job-test", "title": "Job Test", "topic": "Test", "target_duration_seconds": 480},
    )
    started = client.post("/api/projects/job-test/actions/research", json={})
    assert started.status_code == 200
    assert started.json()["status"] == "running"

    state = started.json()
    for _ in range(80):
        state = client.get("/api/projects/job-test/job").json()
        if state["status"] != "running":
            break
        time.sleep(0.05)
    assert state["status"] == "completed"
    project = client.get("/api/projects/job-test").json()
    assert project["state"] == "RESEARCH_READY"
    assert project["next_action"]["id"] == "structure"
    assert "Created ResearchDossier" in client.get("/api/projects/job-test/logs").json()["log"]

def test_studio_rejects_project_path_traversal(tmp_path: Path):
    client = TestClient(create_app(tmp_path / "projects"))
    response = client.get("/api/projects/..%2Fsecrets")
    assert response.status_code == 404

    artifact = client.get("/artifacts/..%2Fsecrets/file.txt")
    assert artifact.status_code == 404



def test_orchestrator_routes_profiles_and_prompt_packs(tmp_path: Path):
    client = TestClient(create_app(tmp_path / "projects"))
    payload = client.get("/api/orchestrator").json()
    assert len(payload["tasks"]) == 17
    assert payload["active_profile"] == "highest_quality"
    assert payload["active_prompt_pack"] == "aviation_investigation"

    changed = client.patch(
        "/api/orchestrator",
        json={
            "active_prompt_pack": "engineering_failure",
            "tasks": {
                "research": {
                    "provider": "mock",
                    "model": "Deterministic Demo",
                    "reasoning_effort": "low",
                    "retry_count": 0,
                    "fallback_provider": "mock",
                    "fallback_model": "Deterministic Demo",
                }
            },
        },
    )
    assert changed.status_code == 200
    updated = changed.json()
    assert updated["active_profile"] == "custom"
    assert updated["active_prompt_pack"] == "engineering_failure"
    research = next(item for item in updated["tasks"] if item["id"] == "research")
    assert research["provider"] == "mock"

    applied = client.post("/api/orchestrator/profiles/offline/apply")
    assert applied.status_code == 200
    assert applied.json()["active_profile"] == "offline"
    assert all(item["provider"] == "mock" for item in applied.json()["tasks"])

    health = client.post("/api/orchestrator/providers/chatgpt_ui/test")
    assert health.status_code == 200
    assert health.json()["healthy"] is True


def test_orchestrator_route_is_recorded_on_real_job(tmp_path: Path):
    workspace = tmp_path / "projects"
    client = TestClient(create_app(workspace))
    client.post(
        "/api/projects",
        json={"project_id": "route-test", "title": "Route Test", "topic": "Test", "target_duration_seconds": 480},
    )
    client.patch(
        "/api/orchestrator",
        json={
            "tasks": {
                "research": {
                    "provider": "mock",
                    "model": "Deterministic Demo",
                    "reasoning_effort": "low",
                    "fallback_provider": "mock",
                    "fallback_model": "Deterministic Demo",
                }
            }
        },
    )
    started = client.post("/api/projects/route-test/actions/research", json={})
    assert started.status_code == 200
    assert started.json()["routing"]["provider"] == "mock"
    assert started.json()["routing"]["model"] == "Deterministic Demo"
    for _ in range(80):
        job = client.get("/api/projects/route-test/job").json()
        if job["status"] != "running":
            break
        time.sleep(0.05)
    assert job["status"] == "completed"
    assert job["routing"]["task_id"] == "research"


def test_orchestrator_rejects_incompatible_capability_route(tmp_path: Path):
    client = TestClient(create_app(tmp_path / "projects"))
    response = client.patch(
        "/api/orchestrator",
        json={"tasks": {"image_generator": {"provider": "codex", "model": "gpt-5.6"}}},
    )
    assert response.status_code == 400
    assert "cannot execute image" in response.json()["detail"]
