from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import wave
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..io import load_model, write_json
from ..models import AudioManifest, ProjectState, V1MediaManifest, utc_now
from .jobs import JobManager
from .service import StudioService

APP_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = APP_ROOT / "static"
SHOT_ID_RE = re.compile(r"SHOT_\d{3}", re.I)


def create_app(workspace: Path | str = "projects") -> FastAPI:
    service = StudioService(workspace)
    jobs = JobManager(service.workspace, service.config, service.orchestrator_config, service.store)
    app = FastAPI(title="Failure Investigation Studio", version="1.0.0")
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

    @app.patch("/api/config")
    def update_config(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            return service.save_config(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
        approvals = {
            "approve_structure": ("structure", ProjectState.STRUCTURE_APPROVED),
            "approve_narration": ("narration", ProjectState.NARRATION_APPROVED),
            "approve_script": ("narration", ProjectState.NARRATION_APPROVED),
            "approve_voice": ("voice", ProjectState.VOICE_APPROVED),
            "approve_shots": ("shots", ProjectState.SHOTS_APPROVED),
        }
        if action in approvals:
            artifact, state = approvals[action]
            if artifact in {"structure", "narration", "shots"}:
                service.store.approve_version(project_id, artifact)
            if action == "approve_shots":
                from ..pipeline import generate_master_assets
                generate_master_assets(service.store, project_id)
            service.store.transition(project_id, state)
            return {"status": "completed", "action": action, "state": state.value}
        payload = payload or {}
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
            consume_stage = "script" if stage == "narration" else stage
            job = jobs.start(project_id, f"consume_{consume_stage}") if payload.get("consume", True) else None
            return {"saved": str(path.relative_to(service.store.project_dir(project_id))), "job": job}
        except (ValueError, FileNotFoundError, json.JSONDecodeError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/assets/{asset_id}/review")
    def asset_review(project_id: str, asset_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        _require_project(service, project_id)
        target = str(payload.get("target", "image"))
        status = str(payload.get("status", "pending"))
        try:
            _set_media_status(service, project_id, asset_id.upper(), target, status)
            return next(item for item in service.assets(project_id)["assets"] if item["asset_id"] == asset_id.upper())
        except (ValueError, StopIteration, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/assets/bulk-review")
    def bulk_review(project_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        _require_project(service, project_id)
        target = str(payload.get("target", "image"))
        status = str(payload.get("status", "approved"))
        asset_ids = list(payload.get("asset_ids", [])) or [item["asset_id"] for item in service.assets(project_id)["assets"]]
        for asset_id in asset_ids:
            _set_media_status(service, project_id, str(asset_id).upper(), target, status)
        if status in {"approved", "rejected"}:
            manifest = _media_manifest(service, project_id, target)
            complete = all(
                item.status == "approved" if target == "image" else item.status in {"approved", "rejected"}
                for item in manifest.jobs
            )
            if complete:
                service.store.transition(project_id, ProjectState.IMAGES_APPROVED if target == "image" else ProjectState.VIDEOS_APPROVED)
        return {"updated": asset_ids, "status": status, "target": target}

    @app.post("/api/projects/{project_id}/upload/images")
    async def upload_images(project_id: str, files: list[UploadFile] = File(...)) -> dict[str, Any]:
        _require_project(service, project_id)
        return await _upload_media(service, project_id, files, "image")

    @app.post("/api/projects/{project_id}/upload/videos")
    async def upload_videos(project_id: str, files: list[UploadFile] = File(...)) -> dict[str, Any]:
        _require_project(service, project_id)
        return await _upload_media(service, project_id, files, "video")

    @app.post("/api/projects/{project_id}/upload/image-batch")
    async def upload_image_batch(project_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
        _require_project(service, project_id)
        if not file.filename or not file.filename.lower().endswith(".zip"):
            raise HTTPException(status_code=400, detail="Upload a ZIP containing shot images named with SHOT_###")
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "batch.zip"
            with archive.open("wb") as handle:
                shutil.copyfileobj(file.file, handle)
            shutil.unpack_archive(str(archive), temp_dir)
            uploads = []
            for path in Path(temp_dir).rglob("*"):
                if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                    uploads.append(path)
            saved = _import_local_media(service, project_id, uploads, "image")
            return {"saved": saved}

    @app.post("/api/projects/{project_id}/upload/narration")
    async def upload_narration(project_id: str, audio: UploadFile = File(...)) -> dict[str, Any]:
        _require_project(service, project_id)
        project = service.store.project_dir(project_id)
        destination = project / "04_voice/voiceover_master.wav"
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as handle:
            shutil.copyfileobj(audio.file, handle)
        try:
            with wave.open(str(destination), "rb") as wav:
                duration = wav.getnframes() / wav.getframerate()
                sample_rate = wav.getframerate()
        except Exception as exc:
            destination.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="Manual narration upload must be a valid WAV file") from exc
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        manifest = AudioManifest(
            project_id=project_id,
            provider="manual_upload",
            model_id="manual",
            voice_id="manual",
            sample_rate=sample_rate,
            duration_seconds=duration,
            voiceover_wav=str(destination.relative_to(project)),
            voiceover_sha256=digest,
            chapters=[],
        )
        write_json(project / "04_voice/audio_manifest.json", manifest)
        service.store.transition(project_id, ProjectState.VOICE_REVIEW)
        return {"audio": str(destination.relative_to(project)), "state": ProjectState.VOICE_REVIEW.value}

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


def _media_manifest(service: StudioService, project_id: str, target: str) -> V1MediaManifest:
    path = service.store.project_dir(project_id) / ("07_images/jobs.json" if target == "image" else "09_videos/jobs.json")
    return load_model(path, V1MediaManifest)


def _set_media_status(service: StudioService, project_id: str, shot_id: str, target: str, status: str) -> None:
    if target not in {"image", "video"}:
        raise ValueError("target must be image or video")
    manifest = _media_manifest(service, project_id, target)
    job = next((item for item in manifest.jobs if item.shot_id == shot_id), None)
    if job is None:
        raise ValueError(f"unknown shot {shot_id}")
    if status not in {"pending", "review", "approved", "rejected", "failed"}:
        raise ValueError("unsupported review status")
    if status == "approved" and (not job.output or not (service.store.project_dir(project_id) / job.output).exists()):
        raise FileNotFoundError(f"cannot approve missing {target} for {shot_id}")
    job.status = status
    job.updated_at = utc_now()
    write_json(service.store.project_dir(project_id) / ("07_images/jobs.json" if target == "image" else "09_videos/jobs.json"), manifest)


async def _upload_media(service: StudioService, project_id: str, files: list[UploadFile], target: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as temp_dir:
        local = []
        for upload in files:
            path = Path(temp_dir) / Path(upload.filename or "upload.bin").name
            with path.open("wb") as handle:
                shutil.copyfileobj(upload.file, handle)
            local.append(path)
        saved = _import_local_media(service, project_id, local, target)
    service.store.transition(project_id, ProjectState.IMAGES_REVIEW if target == "image" else ProjectState.VIDEOS_REVIEW)
    return {"saved": saved, "target": target}


def _import_local_media(service: StudioService, project_id: str, files: list[Path], target: str) -> list[str]:
    project = service.store.project_dir(project_id)
    manifest = _media_manifest(service, project_id, target)
    pending = [item for item in manifest.jobs if item.status not in {"approved"}]
    saved = []
    for source in files:
        match = SHOT_ID_RE.search(source.name)
        shot_id = match.group(0).upper() if match else pending[0].shot_id if pending else None
        if not shot_id:
            continue
        job = next((item for item in manifest.jobs if item.shot_id == shot_id), None)
        if job is None:
            continue
        destination = project / str(job.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        job.status = "review"
        job.error = None
        job.updated_at = utc_now()
        saved.append(str(destination.relative_to(project)))
        pending = [item for item in pending if item.shot_id != shot_id]
    write_json(project / ("07_images/jobs.json" if target == "image" else "09_videos/jobs.json"), manifest)
    return saved


PROJECT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")


def _require_project(service: StudioService, project_id: str) -> None:
    if not PROJECT_ID_PATTERN.fullmatch(project_id) or not service.store.exists(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
