from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..io import load_model, read_json, write_json
from ..models import (
    DocumentaryScript,
    DocumentaryStructure,
    MasterAssetPlan,
    ProjectBrief,
    ProjectManifest,
    ProjectState,
    ResearchDossier,
    ShotPlan,
    Timeline,
)
from ..project import ProjectStore
from ..orchestrator import (
    apply_profile,
    merge_orchestrator_config,
    public_payload as orchestrator_public_payload,
    provider_health,
    resolve_task,
)
from ..review import approval_summary


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


STATE_ORDER = [
    ProjectState.PROJECT_CREATED,
    ProjectState.RESEARCH_READY,
    ProjectState.STRUCTURE_REVIEW,
    ProjectState.STRUCTURE_APPROVED,
    ProjectState.SCRIPT_REVIEW,
    ProjectState.SCRIPT_APPROVED,
    ProjectState.SHOT_PLAN_READY,
    ProjectState.ASSET_PLAN_READY,
    ProjectState.IMAGE_GENERATION,
    ProjectState.IMAGE_REVIEW,
    ProjectState.IMAGES_APPROVED,
    ProjectState.VIDEO_GENERATION,
    ProjectState.VIDEO_REVIEW,
    ProjectState.VIDEOS_APPROVED,
    ProjectState.NARRATION_READY,
    ProjectState.PREVIEW_REVIEW,
    ProjectState.PICTURE_LOCKED,
]
STATE_INDEX = {state: index for index, state in enumerate(STATE_ORDER)}


@dataclass(frozen=True)
class StageDefinition:
    id: str
    number: int
    title: str
    short_title: str
    description: str
    states: tuple[ProjectState, ...]
    artifact_paths: tuple[str, ...]


STAGES = [
    StageDefinition(
        "research", 1, "Research dossier", "Research",
        "Ground the story with a timeline, sources, evidence and a claim ledger.",
        (ProjectState.PROJECT_CREATED, ProjectState.RESEARCH_READY),
        ("01_research/source_summary.md", "01_research/source_dossier.json", "01_research/claim_ledger.json"),
    ),
    StageDefinition(
        "structure", 2, "Story architecture", "Structure",
        "Shape the cold open, reveals, escalation, theories and human ending.",
        (ProjectState.RESEARCH_READY, ProjectState.STRUCTURE_REVIEW, ProjectState.STRUCTURE_APPROVED),
        ("02_structure/structure.md", "02_structure/structure.json"),
    ),
    StageDefinition(
        "script", 3, "Narration script", "Script",
        "Write the complete narration while keeping every factual claim traceable.",
        (ProjectState.STRUCTURE_APPROVED, ProjectState.SCRIPT_REVIEW, ProjectState.SCRIPT_APPROVED),
        ("03_script/script.md", "03_script/script.json"),
    ),
    StageDefinition(
        "shots", 4, "Shot design", "Shots",
        "Divide narration into visual beats and compress them into reusable master assets.",
        (ProjectState.SCRIPT_APPROVED, ProjectState.SHOT_PLAN_READY, ProjectState.ASSET_PLAN_READY),
        ("04_shot_plan/shot_plan.md", "04_shot_plan/shot_plan.json", "05_master_assets/coverage_report.json"),
    ),
    StageDefinition(
        "image_factory", 5, "Image factory", "Images",
        "Generate master stills automatically with Grok CLI or export a resumable subscription-UI packet.",
        (ProjectState.ASSET_PLAN_READY, ProjectState.IMAGE_GENERATION),
        ("05_master_assets/master_assets.json", "08_generated_images/generation_report.json", "07_review/image_factory_packet/PRODUCTION_PACKET.md"),
    ),
    StageDefinition(
        "image_review", 6, "Image approval", "Review",
        "Review continuity, composition and animation readiness asset by asset.",
        (ProjectState.IMAGE_GENERATION, ProjectState.IMAGE_REVIEW, ProjectState.IMAGES_APPROVED),
        ("06_contact_sheet/contact_sheet.png", "08_generated_images/import_report.json"),
    ),
    StageDefinition(
        "video_factory", 7, "Video factory", "Videos",
        "Create motion jobs, generate clips through the selected provider, and approve only failed exceptions.",
        (ProjectState.IMAGES_APPROVED, ProjectState.VIDEO_GENERATION, ProjectState.VIDEO_REVIEW, ProjectState.VIDEOS_APPROVED),
        ("09_video_jobs/video_jobs.json", "10_generated_videos/generation_report.json", "10_generated_videos/import_report.json"),
    ),
    StageDefinition(
        "assembly", 8, "Narration & assembly", "Assembly",
        "Multiply footage, attach narration, build the timeline and render the picture-locked base.",
        (ProjectState.VIDEOS_APPROVED, ProjectState.NARRATION_READY, ProjectState.PREVIEW_REVIEW, ProjectState.PICTURE_LOCKED),
        ("12_timeline/timeline.json", "13_preview/composition/index.html", "13_preview/preview_v01.mp4", "14_final/picture_locked_base.mp4"),
    ),
]


DEFAULT_CONFIG: dict[str, Any] = {
    "agent_mode": "manual",
    "command_template": "codex exec --skip-git-repo-check --output-last-message {output} - < {prompt}",
    "default_duration": 480,
    "default_max_assets": 28,
    "auto_refresh_seconds": 2,
    "theme": "dark",
}


class StudioService:
    def __init__(self, workspace: Path | str = "projects") -> None:
        self.store = ProjectStore(workspace)
        self.workspace = self.store.workspace
        self.workspace.mkdir(parents=True, exist_ok=True)

    @property
    def config_path(self) -> Path:
        return self.workspace / ".fde-studio.json"

    @property
    def orchestrator_path(self) -> Path:
        return self.workspace / ".fde-orchestrator.json"

    def orchestrator_config(self) -> dict[str, Any]:
        saved: dict[str, Any] = {}
        if self.orchestrator_path.exists():
            try:
                saved = read_json(self.orchestrator_path)
            except Exception:
                saved = {}
        return merge_orchestrator_config(saved)

    def orchestrator(self) -> dict[str, Any]:
        return orchestrator_public_payload(self.orchestrator_config())

    def save_orchestrator(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.orchestrator_config()
        if "active_prompt_pack" in payload:
            pack = str(payload["active_prompt_pack"])
            if pack not in current.get("prompt_packs", {}):
                raise ValueError(f"Unknown prompt pack: {pack}")
            current["active_prompt_pack"] = pack
        if isinstance(payload.get("tasks"), dict):
            current["active_profile"] = "custom"
            for task_id, values in payload["tasks"].items():
                if task_id not in current["tasks"] or not isinstance(values, dict):
                    continue
                current["tasks"][task_id].update(values)
        if isinstance(payload.get("providers"), dict):
            for provider_id, values in payload["providers"].items():
                if provider_id not in current["providers"] or not isinstance(values, dict):
                    continue
                current["providers"][provider_id].update(values)
        if isinstance(payload.get("prompt_packs"), dict):
            for pack_id, values in payload["prompt_packs"].items():
                if pack_id not in current["prompt_packs"] or not isinstance(values, dict):
                    continue
                current["prompt_packs"][pack_id].update(values)
        if isinstance(payload.get("rules"), list):
            current["rules"] = payload["rules"]
        # Reject incompatible routes at save time, not when a paid job starts.
        for task_id in current.get("tasks", {}):
            resolve_task(current, task_id, {})
        write_json(self.orchestrator_path, current)
        return self.orchestrator()

    def apply_orchestrator_profile(self, profile_id: str) -> dict[str, Any]:
        current = apply_profile(self.orchestrator_config(), profile_id)
        write_json(self.orchestrator_path, current)
        return self.orchestrator()

    def test_orchestrator_provider(self, provider_id: str) -> dict[str, Any]:
        current = self.orchestrator_config()
        return provider_health(provider_id, current.get("providers", {}).get(provider_id)) | {"checked_at": utc_now()}

    def config(self) -> dict[str, Any]:
        config = dict(DEFAULT_CONFIG)
        if self.config_path.exists():
            try:
                config.update(read_json(self.config_path))
            except Exception:
                pass
        config["capabilities"] = {
            "ffmpeg": shutil.which("ffmpeg") is not None,
            "ffprobe": shutil.which("ffprobe") is not None,
            "codex": shutil.which("codex") is not None,
            "grok": shutil.which("grok") is not None,
            "hyperframes": bool(shutil.which("hyperframes") or (Path(__file__).resolve().parents[2] / "node_modules/.bin/hyperframes").exists() or shutil.which("npx")),
        }
        config["command_configured"] = bool(config.get("command_template"))
        return config

    def save_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "agent_mode", "command_template", "default_duration", "default_max_assets",
            "auto_refresh_seconds", "theme",
        }
        current = self.config()
        current.pop("capabilities", None)
        current.pop("command_configured", None)
        for key, value in payload.items():
            if key in allowed:
                current[key] = value
        if current.get("agent_mode") not in {"manual", "command", "mock"}:
            raise ValueError("agent_mode must be manual, command, or mock")
        current["default_duration"] = max(60, min(3600, int(current.get("default_duration", 480))))
        current["default_max_assets"] = max(1, min(60, int(current.get("default_max_assets", 28))))
        current["auto_refresh_seconds"] = max(1, min(30, int(current.get("auto_refresh_seconds", 2))))
        write_json(self.config_path, current)
        return self.config()

    def project_ids(self) -> list[str]:
        if not self.workspace.exists():
            return []
        projects = []
        for path in self.workspace.iterdir():
            if path.is_dir() and (path / "project_manifest.json").exists():
                projects.append(path.name)
        return sorted(projects, key=lambda item: self.store.manifest(item).updated_at, reverse=True)

    def bootstrap(self) -> dict[str, Any]:
        projects = [self.project_summary(project_id) for project_id in self.project_ids()]
        totals = {
            "projects": len(projects),
            "in_review": sum(1 for item in projects if "REVIEW" in item["state"]),
            "picture_locked": sum(1 for item in projects if item["state"] == ProjectState.PICTURE_LOCKED.value),
            "assets": sum(item["metrics"]["assets"] for item in projects),
        }
        return {
            "projects": projects,
            "totals": totals,
            "config": self.config(),
            "stage_definitions": [self._stage_definition_payload(stage) for stage in STAGES],
            "orchestrator": self.orchestrator(),
        }

    def create_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        tone_value = payload.get("tone", ["investigative", "suspenseful", "respectful"])
        if isinstance(tone_value, str):
            tone = [part.strip() for part in tone_value.split(",") if part.strip()]
        else:
            tone = list(tone_value or [])
        brief = ProjectBrief(
            project_id=str(payload.get("project_id", "")).strip(),
            title=str(payload.get("title", "")).strip() or "Untitled Failure Investigation",
            topic=str(payload.get("topic", "")).strip() or str(payload.get("title", "")).strip(),
            target_duration_seconds=float(payload.get("target_duration_seconds", 480)),
            maximum_master_assets=int(payload.get("maximum_master_assets", 28)),
            master_video_duration_seconds=float(payload.get("master_video_duration_seconds", 5)),
            language=str(payload.get("language", "English")),
            audience=str(payload.get("audience", "General international audience")),
            tone=tone or ["investigative", "suspenseful", "respectful"],
        )
        self.store.create(brief)
        return self.project_detail(brief.project_id)

    def project_summary(self, project_id: str) -> dict[str, Any]:
        brief = self.store.brief(project_id)
        manifest = self.store.manifest(project_id)
        metrics = self.metrics(project_id)
        progress = self.progress_percent(manifest.state)
        next_action = self.next_action(project_id)
        preview = self._existing_relative(project_id, [
            "06_contact_sheet/contact_sheet.png",
            "08_generated_images/thumbnails/A01.jpg",
        ])
        return {
            "project_id": project_id,
            "title": brief.title,
            "topic": brief.topic,
            "state": manifest.state.value,
            "state_label": state_label(manifest.state),
            "updated_at": manifest.updated_at,
            "created_at": brief.created_at,
            "duration_seconds": brief.target_duration_seconds,
            "max_assets": brief.maximum_master_assets,
            "progress": progress,
            "metrics": metrics,
            "next_action": next_action,
            "preview_url": self.artifact_url(project_id, preview) if preview else None,
        }

    def project_detail(self, project_id: str) -> dict[str, Any]:
        brief = self.store.brief(project_id)
        manifest = self.store.manifest(project_id)
        summary = self.project_summary(project_id)
        stages = [self.stage_status(project_id, stage) for stage in STAGES]
        artifacts = self.artifacts(project_id)
        detail = {
            **summary,
            "brief": brief.model_dump(mode="json"),
            "manifest": manifest.model_dump(mode="json"),
            "stages": stages,
            "artifacts": artifacts,
            "approval_summary": self.safe_approval_summary(project_id),
            "manual_requests": self.manual_requests(project_id),
            "contact_sheet_url": self.optional_artifact_url(project_id, "06_contact_sheet/contact_sheet.png"),
            "preview_video_url": self.optional_artifact_url(project_id, "13_preview/preview_v01.mp4"),
            "final_video_url": self.optional_artifact_url(project_id, "14_final/picture_locked_base.mp4"),
            "image_factory_zip_url": self.optional_artifact_url(project_id, f"07_review/{project_id}_image_factory_packet.zip"),
            "image_factory_packet_ready": (self.store.project_dir(project_id) / "07_review/image_factory_packet/ASSET_MANIFEST.json").exists(),
            "task_routes": self._project_task_routes(project_id),
            "image_generation_report": self._optional_json(project_id, "08_generated_images/generation_report.json"),
            "video_generation_report": self._optional_json(project_id, "10_generated_videos/generation_report.json"),
        }
        return detail

    def metrics(self, project_id: str) -> dict[str, int | float]:
        project = self.store.project_dir(project_id)
        result: dict[str, int | float] = {
            "chapters": 0, "script_words": 0, "shots": 0, "assets": 0,
            "images": 0, "images_approved": 0, "videos": 0, "videos_approved": 0,
            "timeline_entries": 0,
        }
        try:
            structure = load_model(project / "02_structure/structure.json", DocumentaryStructure)
            result["chapters"] = len(structure.chapters)
        except Exception:
            pass
        try:
            script = load_model(project / "03_script/script.json", DocumentaryScript)
            result["script_words"] = script.estimated_word_count
        except Exception:
            pass
        try:
            shots = load_model(project / "04_shot_plan/shot_plan.json", ShotPlan)
            result["shots"] = len(shots.shots)
        except Exception:
            pass
        try:
            assets = load_model(project / "05_master_assets/master_assets.json", MasterAssetPlan)
            result["assets"] = len(assets.assets)
            result["images"] = sum(1 for item in assets.assets if item.approved_image)
            result["images_approved"] = sum(1 for item in assets.assets if item.image_review.status.value == "approved")
            result["videos"] = sum(1 for item in assets.assets if item.approved_video)
            result["videos_approved"] = sum(1 for item in assets.assets if item.video_review.status.value == "approved")
        except Exception:
            pass
        try:
            timeline = load_model(project / "12_timeline/timeline.json", Timeline)
            result["timeline_entries"] = len(timeline.entries)
        except Exception:
            pass
        return result

    def _resolved_route(self, project_id: str, task_id: str) -> dict[str, Any]:
        brief = self.store.brief(project_id)
        return resolve_task(self.orchestrator_config(), task_id, {
            "duration_seconds": brief.target_duration_seconds,
            "topic": brief.topic,
            "title": brief.title,
        })

    def _project_task_routes(self, project_id: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for task_id in ("research", "structure", "script", "shot_planner", "image_generator", "video_generator", "composition_renderer"):
            try:
                route = self._resolved_route(project_id, task_id)
                result[task_id] = {
                    "provider": route.get("provider"), "provider_label": route.get("provider_label"),
                    "provider_mode": route.get("provider_mode"), "model": route.get("model"),
                    "capability": route.get("capability"),
                }
            except Exception as exc:
                result[task_id] = {"error": str(exc)}
        return result

    def _optional_json(self, project_id: str, relative: str) -> dict[str, Any] | None:
        path = self.store.project_dir(project_id) / relative
        if not path.exists():
            return None
        try:
            return read_json(path)
        except Exception:
            return None

    def safe_approval_summary(self, project_id: str) -> dict[str, Any]:
        try:
            return approval_summary(self.store.project_dir(project_id))
        except Exception:
            return {
                "total_assets": 0, "missing_images": [], "pending_image_reviews": [],
                "missing_videos": [], "pending_video_reviews": [], "uncovered_shots": [],
            }

    def progress_percent(self, state: ProjectState) -> int:
        if state == ProjectState.PICTURE_LOCKED:
            return 100
        index = STATE_INDEX.get(state, 0)
        return min(99, round(index / (len(STATE_ORDER) - 1) * 100))

    def stage_status(self, project_id: str, stage: StageDefinition) -> dict[str, Any]:
        manifest = self.store.manifest(project_id)
        current = manifest.state
        stage_indexes = [STATE_INDEX[state] for state in stage.states]
        current_index = STATE_INDEX.get(current, 0)
        first, last = min(stage_indexes), max(stage_indexes)
        if current_index > last:
            status = "complete"
        elif current_index < first:
            status = "locked"
        else:
            status = "active"
        if current in stage.states and "REVIEW" in current.value:
            status = "review"
        artifacts = []
        project = self.store.project_dir(project_id)
        for relative in stage.artifact_paths:
            path = project / relative
            if path.exists():
                artifacts.append({
                    "name": path.name,
                    "path": relative,
                    "url": self.artifact_url(project_id, relative),
                    "kind": artifact_kind(path),
                    "size": path.stat().st_size,
                })
        return {
            **self._stage_definition_payload(stage),
            "status": status,
            "artifacts": artifacts,
            "action": self.stage_action(project_id, stage.id),
        }

    def stage_action(self, project_id: str, stage_id: str) -> dict[str, Any] | None:
        next_action = self.next_action(project_id)
        if next_action and next_action.get("stage") == stage_id:
            return next_action
        return None

    def next_action(self, project_id: str) -> dict[str, Any] | None:
        state = self.store.manifest(project_id).state
        project = self.store.project_dir(project_id)
        summary = self.safe_approval_summary(project_id)
        if state == ProjectState.IMAGE_REVIEW:
            if summary.get("missing_images") or summary.get("pending_image_reviews"):
                return action("review_images", "image_review", "Review generated images", "navigate")
            return action("validate_assets", "image_review", "Lock approved images", "validate")
        if state == ProjectState.VIDEO_GENERATION:
            route = self._resolved_route(project_id, "video_generator")
            if route.get("provider_mode") in {"manual"} or route.get("provider") in {"grok_ui", "manual_upload"}:
                return action("upload_videos", "video_factory", "Upload generated videos", "navigate")
            return action("generate_videos", "video_factory", f"Generate videos with {route.get('provider_label', 'selected provider')}", "run")
        if state == ProjectState.VIDEO_REVIEW:
            if summary.get("missing_videos") or summary.get("pending_video_reviews"):
                return action("review_videos", "video_factory", "Review generated videos", "navigate")
            return action("validate_videos", "video_factory", "Lock approved videos", "validate")
        if state == ProjectState.VIDEOS_APPROVED:
            if (project / "10_generated_videos/variants/variant_manifest.json").exists():
                return action("import_narration", "assembly", "Import narration", "navigate")
            return action("create_variants", "assembly", "Create footage variants", "run")
        if state == ProjectState.NARRATION_READY:
            if (project / "12_timeline/timeline.json").exists():
                return action("render_preview", "assembly", "Render narrated preview", "render")
            return action("build_timeline", "assembly", "Build narration timeline", "run")
        mapping: dict[ProjectState, dict[str, Any]] = {
            ProjectState.PROJECT_CREATED: action("research", "research", "Build research dossier", "run"),
            ProjectState.RESEARCH_READY: action("structure", "structure", "Create story structure", "run"),
            ProjectState.STRUCTURE_REVIEW: action("approve_structure", "structure", "Approve structure", "approve"),
            ProjectState.STRUCTURE_APPROVED: action("script", "script", "Write narration script", "run"),
            ProjectState.SCRIPT_REVIEW: action("approve_script", "script", "Approve script", "approve"),
            ProjectState.SCRIPT_APPROVED: action("shots", "shots", "Design shot divisions", "run"),
            ProjectState.SHOT_PLAN_READY: action("optimize_assets", "shots", "Compress to master assets", "run"),
            ProjectState.ASSET_PLAN_READY: action("generate_image_prompts", "image_factory", "Generate image packet", "run"),
            ProjectState.IMAGE_GENERATION: (
                action("export_image_factory", "image_factory", "Export subscription-UI packet", "export")
                if self._resolved_route(project_id, "image_generator").get("provider_mode") == "manual"
                else action("generate_images", "image_factory", f"Generate images with {self._resolved_route(project_id, 'image_generator').get('provider_label', 'selected provider')}", "run")
            ),
            ProjectState.IMAGES_APPROVED: action("video_jobs", "video_factory", "Create Grok video jobs", "run"),
            ProjectState.PREVIEW_REVIEW: action("render_final", "assembly", "Render picture-locked base", "render"),
        }
        return mapping.get(state)

    def assets(self, project_id: str) -> dict[str, Any]:
        project = self.store.project_dir(project_id)
        path = project / "05_master_assets/master_assets.json"
        if not path.exists():
            return {"assets": [], "summary": self.safe_approval_summary(project_id)}
        plan = load_model(path, MasterAssetPlan)
        shot_lookup: dict[str, Any] = {}
        shot_path = project / "04_shot_plan/shot_plan.json"
        if shot_path.exists():
            shots = load_model(shot_path, ShotPlan)
            shot_lookup = {item.shot_id: item.model_dump(mode="json") for item in shots.shots}
        assets = []
        for item in plan.assets:
            image_url = self.artifact_url(project_id, item.approved_image) if item.approved_image else None
            video_url = self.artifact_url(project_id, item.approved_video) if item.approved_video else None
            assets.append({
                **item.model_dump(mode="json"),
                "image_url": image_url,
                "video_url": video_url,
                "shots": [shot_lookup[shot_id] for shot_id in item.linked_shots if shot_id in shot_lookup],
            })
        return {"assets": assets, "summary": self.safe_approval_summary(project_id), "maximum_assets": plan.maximum_assets}

    def timeline(self, project_id: str) -> dict[str, Any]:
        project = self.store.project_dir(project_id)
        path = project / "12_timeline/timeline.json"
        if not path.exists():
            return {"entries": [], "total_seconds": 0}
        timeline = load_model(path, Timeline)
        payload = timeline.model_dump(mode="json")
        for entry in payload["entries"]:
            if entry.get("source_media"):
                entry["source_url"] = self.artifact_url(project_id, entry["source_media"])
        return payload

    def artifacts(self, project_id: str) -> list[dict[str, Any]]:
        project = self.store.project_dir(project_id)
        results: list[dict[str, Any]] = []
        if not project.exists():
            return results
        allowed_suffixes = {".json", ".md", ".txt", ".png", ".jpg", ".jpeg", ".webp", ".pdf", ".html", ".mp4", ".wav", ".zip"}
        for path in project.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in allowed_suffixes:
                continue
            relative = path.relative_to(project).as_posix()
            if "/_render/" in f"/{relative}/" or relative.startswith("_requests/") and path.name.endswith("_schema.json"):
                continue
            results.append({
                "name": path.name,
                "path": relative,
                "stage": relative.split("/", 1)[0],
                "kind": artifact_kind(path),
                "size": path.stat().st_size,
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                "url": self.artifact_url(project_id, relative),
            })
        return sorted(results, key=lambda item: item["updated_at"], reverse=True)

    def manual_requests(self, project_id: str) -> list[dict[str, Any]]:
        request_dir = self.store.project_dir(project_id) / "_requests"
        results = []
        if not request_dir.exists():
            return results
        for prompt in sorted(request_dir.glob("*_prompt.md")):
            stage = prompt.stem.replace("_prompt", "")
            response = request_dir / f"{stage}_response.json"
            schema = request_dir / f"{stage}_schema.json"
            results.append({
                "stage": stage,
                "prompt_url": self.artifact_url(project_id, prompt.relative_to(self.store.project_dir(project_id)).as_posix()),
                "schema_url": self.artifact_url(project_id, schema.relative_to(self.store.project_dir(project_id)).as_posix()) if schema.exists() else None,
                "response_exists": response.exists(),
                "response_url": self.artifact_url(project_id, response.relative_to(self.store.project_dir(project_id)).as_posix()) if response.exists() else None,
            })
        return results

    def save_manual_response(self, project_id: str, stage: str, value: Any) -> Path:
        if stage not in {"research", "structure", "script", "shots"}:
            raise ValueError("unsupported manual stage")
        project = self.store.project_dir(project_id)
        schema_path = project / f"_requests/{stage}_schema.json"
        if not schema_path.exists():
            raise FileNotFoundError("Generate the manual request before saving a response")
        path = project / f"_requests/{stage}_response.json"
        if isinstance(value, str):
            value = json.loads(value)
        write_json(path, value)
        return path

    def artifact_url(self, project_id: str, relative: str | None) -> str | None:
        if not relative:
            return None
        return f"/artifacts/{project_id}/{relative}"

    def optional_artifact_url(self, project_id: str, relative: str) -> str | None:
        return self.artifact_url(project_id, relative) if (self.store.project_dir(project_id) / relative).exists() else None

    def _existing_relative(self, project_id: str, candidates: list[str]) -> str | None:
        project = self.store.project_dir(project_id)
        return next((item for item in candidates if (project / item).exists()), None)

    @staticmethod
    def _stage_definition_payload(stage: StageDefinition) -> dict[str, Any]:
        return {
            "id": stage.id, "number": stage.number, "title": stage.title,
            "short_title": stage.short_title, "description": stage.description,
        }


def action(action_id: str, stage: str, label: str, kind: str) -> dict[str, Any]:
    return {"id": action_id, "stage": stage, "label": label, "kind": kind}


def state_label(state: ProjectState) -> str:
    labels = {
        ProjectState.PROJECT_CREATED: "Ready for research",
        ProjectState.RESEARCH_READY: "Research ready",
        ProjectState.STRUCTURE_REVIEW: "Structure review",
        ProjectState.STRUCTURE_APPROVED: "Structure approved",
        ProjectState.SCRIPT_REVIEW: "Script review",
        ProjectState.SCRIPT_APPROVED: "Script approved",
        ProjectState.SHOT_PLAN_READY: "Shot plan ready",
        ProjectState.ASSET_PLAN_READY: "Asset plan ready",
        ProjectState.IMAGE_GENERATION: "Image generation",
        ProjectState.IMAGE_REVIEW: "Image review",
        ProjectState.IMAGES_APPROVED: "Images approved",
        ProjectState.VIDEO_GENERATION: "Video generation",
        ProjectState.VIDEO_REVIEW: "Video review",
        ProjectState.VIDEOS_APPROVED: "Videos approved",
        ProjectState.NARRATION_READY: "Narration ready",
        ProjectState.PREVIEW_REVIEW: "Preview review",
        ProjectState.PICTURE_LOCKED: "Picture locked",
    }
    return labels[state]


def artifact_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return "image"
    if suffix in {".mp4", ".mov", ".webm"}:
        return "video"
    if suffix in {".wav", ".mp3", ".m4a"}:
        return "audio"
    if suffix == ".zip":
        return "archive"
    if suffix in {".json", ".md", ".txt", ".html", ".pdf"}:
        return "document"
    return "file"
