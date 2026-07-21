from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..assets import import_images
from ..image_factory import import_image_factory_batch
from ..io import load_model, safe_copy, write_json
from ..media import import_videos
from ..models import MasterAssetPlan, ProjectState, ReviewStatus
from ..review import review_asset
from .jobs import JobManager
from .service import StudioService


APP_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = APP_ROOT / "static"


def create_app(workspace: Path | str = "projects") -> FastAPI:
    service = StudioService(workspace)
    jobs = JobManager(service.workspace, service.config, service.orchestrator_config, service.store)
    app = FastAPI(title="Failure Investigation Studio", version="0.5.0")
    app.state.service = service
    app.state.jobs = jobs

    @app.get("/api/bootstrap")
    def bootstrap() -> dict[str, Any]:
        payload = service.bootstrap()
        payload["jobs"] = {project_id: jobs.state(project_id) for project_id in service.project_ids()}
        return payload

    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        return service.config()

    @app.get("/api/orchestrator")
    def get_orchestrator() -> dict[str, Any]:
        return service.orchestrator()

    @app.patch("/api/orchestrator")
    def update_orchestrator(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            return service.save_orchestrator(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/orchestrator/profiles/{profile_id}/apply")
    def apply_orchestrator_profile(profile_id: str) -> dict[str, Any]:
        try:
            return service.apply_orchestrator_profile(profile_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/orchestrator/providers/{provider_id}/test")
    def test_orchestrator_provider(provider_id: str) -> dict[str, Any]:
        try:
            return service.test_orchestrator_provider(provider_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/api/config")
    def update_config(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            return service.save_config(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/projects")
    def list_projects() -> list[dict[str, Any]]:
        return [service.project_summary(project_id) for project_id in service.project_ids()]

    @app.post("/api/projects", status_code=201)
    def create_project(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            return service.create_project(payload)
        except (ValueError, FileExistsError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}")
    def project_detail(project_id: str) -> dict[str, Any]:
        _require_project(service, project_id)
        payload = service.project_detail(project_id)
        payload["job"] = jobs.state(project_id)
        return payload

    @app.get("/api/projects/{project_id}/assets")
    def assets(project_id: str) -> dict[str, Any]:
        _require_project(service, project_id)
        return service.assets(project_id)

    @app.get("/api/projects/{project_id}/timeline")
    def timeline(project_id: str) -> dict[str, Any]:
        _require_project(service, project_id)
        return service.timeline(project_id)

    @app.get("/api/projects/{project_id}/artifacts")
    def artifacts(project_id: str) -> list[dict[str, Any]]:
        _require_project(service, project_id)
        return service.artifacts(project_id)

    @app.get("/api/projects/{project_id}/job")
    def job_state(project_id: str) -> dict[str, Any]:
        _require_project(service, project_id)
        return jobs.state(project_id)

    @app.get("/api/projects/{project_id}/logs")
    def logs(project_id: str, lines: int = 180) -> dict[str, Any]:
        _require_project(service, project_id)
        return {"job": jobs.state(project_id), "log": jobs.log_tail(project_id, lines)}

    @app.post("/api/projects/{project_id}/actions/{action}")
    def run_action(project_id: str, action: str, payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        _require_project(service, project_id)
        payload = payload or {}
        if action == "approve_structure":
            service.store.approve_version(project_id, "structure")
            service.store.transition(project_id, ProjectState.STRUCTURE_APPROVED)
            return {"status": "completed", "action": action}
        if action == "approve_script":
            service.store.approve_version(project_id, "script")
            service.store.transition(project_id, ProjectState.SCRIPT_APPROVED)
            return {"status": "completed", "action": action}
        if action == "refresh_contact_sheet":
            action = "contact_sheet"
        try:
            return jobs.start(project_id, action, agent=payload.get("agent"))
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/stop")
    def stop(project_id: str) -> dict[str, Any]:
        _require_project(service, project_id)
        return jobs.stop(project_id)

    @app.post("/api/projects/{project_id}/manual-response/{stage}")
    def save_manual_response(project_id: str, stage: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        _require_project(service, project_id)
        try:
            value = payload.get("response", payload)
            path = service.save_manual_response(project_id, stage, value)
            if payload.get("consume", True):
                job = jobs.start(project_id, f"consume_{stage}")
            else:
                job = None
            return {"saved": str(path.relative_to(service.store.project_dir(project_id))), "job": job}
        except (ValueError, FileNotFoundError, json.JSONDecodeError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/assets/{asset_id}/review")
    def asset_review(project_id: str, asset_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        _require_project(service, project_id)
        try:
            status = ReviewStatus(payload.get("status", "pending"))
            plan = review_asset(
                service.store,
                project_id,
                asset_id,
                status,
                str(payload.get("instruction", "")),
                list(payload.get("preserve", [])),
                str(payload.get("target", "image")),
            )
            asset = next(item for item in plan.assets if item.asset_id == asset_id)
            return asset.model_dump(mode="json")
        except (ValueError, StopIteration) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/assets/bulk-review")
    def bulk_review(project_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        _require_project(service, project_id)
        target = str(payload.get("target", "image"))
        status = ReviewStatus(payload.get("status", "approved"))
        asset_ids = list(payload.get("asset_ids", []))
        if not asset_ids:
            data = service.assets(project_id)
            asset_ids = [
                item["asset_id"] for item in data["assets"]
                if (item.get("approved_image") if target == "image" else item.get("approved_video"))
            ]
        updated = []
        for asset_id in asset_ids:
            review_asset(service.store, project_id, asset_id, status, target=target)
            updated.append(asset_id)
        return {"updated": updated, "status": status.value, "target": target}

    @app.post("/api/projects/{project_id}/upload/image-batch")
    async def upload_image_batch(project_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
        _require_project(service, project_id)
        if not file.filename or not file.filename.lower().endswith(".zip"):
            raise HTTPException(status_code=400, detail="Upload a ZIP returned by the Image Factory")
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as handle:
            temp = Path(handle.name)
            shutil.copyfileobj(file.file, handle)
        try:
            report = import_image_factory_batch(service.store.project_dir(project_id), temp)
            service.store.transition(project_id, ProjectState.IMAGE_REVIEW)
            return report
        finally:
            temp.unlink(missing_ok=True)

    @app.post("/api/projects/{project_id}/upload/images")
    async def upload_images(project_id: str, files: list[UploadFile] = File(...)) -> dict[str, Any]:
        _require_project(service, project_id)
        inbox = service.store.project_dir(project_id) / "08_generated_images/inbox"
        saved = await _save_uploads(files, inbox)
        report = import_images(service.store.project_dir(project_id))
        service.store.transition(project_id, ProjectState.IMAGE_REVIEW)
        return {"saved": saved, **report}

    @app.post("/api/projects/{project_id}/upload/videos")
    async def upload_videos(project_id: str, files: list[UploadFile] = File(...)) -> dict[str, Any]:
        _require_project(service, project_id)
        inbox = service.store.project_dir(project_id) / "10_generated_videos/inbox"
        saved = await _save_uploads(files, inbox)
        duration = service.store.brief(project_id).master_video_duration_seconds
        report = import_videos(service.store.project_dir(project_id), duration)
        service.store.transition(project_id, ProjectState.VIDEO_REVIEW)
        return {"saved": saved, **report}

    @app.post("/api/projects/{project_id}/upload/narration")
    async def upload_narration(
        project_id: str,
        audio: UploadFile = File(...),
        timestamps: UploadFile | None = File(default=None),
    ) -> dict[str, Any]:
        _require_project(service, project_id)
        project = service.store.project_dir(project_id)
        suffix = Path(audio.filename or "narration.wav").suffix.lower() or ".wav"
        destination = project / f"11_narration/narration_master{suffix}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as handle:
            shutil.copyfileobj(audio.file, handle)
        if timestamps is not None:
            raw = await timestamps.read()
            try:
                data = json.loads(raw.decode("utf-8"))
            except Exception as exc:
                raise HTTPException(status_code=400, detail="Timestamps must be valid JSON") from exc
            write_json(project / "11_narration/word_timestamps.json", data)
        service.store.transition(project_id, ProjectState.NARRATION_READY)
        return {"audio": str(destination.relative_to(project)), "state": ProjectState.NARRATION_READY.value}

    @app.get("/artifacts/{project_id}/{relative_path:path}")
    def artifact(project_id: str, relative_path: str):
        _require_project(service, project_id)
        base = service.store.project_dir(project_id).resolve()
        target = (base / relative_path).resolve()
        if target != base and base not in target.parents:
            raise HTTPException(status_code=404)
        if not target.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(target)

    app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")

    @app.get("/{path:path}", response_class=HTMLResponse)
    def spa(path: str = "") -> HTMLResponse:
        if path.startswith("api/") or path.startswith("artifacts/"):
            raise HTTPException(status_code=404)
        return HTMLResponse((STATIC_ROOT / "index.html").read_text(encoding="utf-8"))

    return app


async def _save_uploads(files: list[UploadFile], inbox: Path) -> list[str]:
    inbox.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for upload in files:
        name = Path(upload.filename or "upload.bin").name
        if not name:
            continue
        target = inbox / name
        with target.open("wb") as handle:
            shutil.copyfileobj(upload.file, handle)
        saved.append(name)
    return saved


PROJECT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")


def _require_project(service: StudioService, project_id: str) -> None:
    if not PROJECT_ID_PATTERN.fullmatch(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    if not service.store.exists(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
