from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ..io import load_model, read_json, write_json
from ..models import (
    AudioManifest,
    AudioTiming,
    DocumentaryScript,
    DocumentaryStructure,
    ProjectBrief,
    ProjectState,
    ShotPlan,
    V1MediaManifest,
)
from ..orchestrator import (
    apply_profile,
    merge_orchestrator_config,
    provider_health,
    public_payload as orchestrator_public_payload,
    resolve_task,
)
from ..project import ProjectStore


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


STATE_ORDER = [
    ProjectState.PROJECT_CREATED,
    ProjectState.RESEARCH_READY,
    ProjectState.STRUCTURE_REVIEW,
    ProjectState.STRUCTURE_APPROVED,
    ProjectState.NARRATION_REVIEW,
    ProjectState.NARRATION_APPROVED,
    ProjectState.VOICE_GENERATING,
    ProjectState.VOICE_REVIEW,
    ProjectState.VOICE_APPROVED,
    ProjectState.SHOTS_GENERATING,
    ProjectState.SHOTS_REVIEW,
    ProjectState.SHOTS_APPROVED,
    ProjectState.IMAGES_GENERATING,
    ProjectState.IMAGES_REVIEW,
    ProjectState.IMAGES_APPROVED,
    ProjectState.ANIMATIC_READY,
    ProjectState.ANIMATIC_APPROVED,
    ProjectState.VIDEOS_GENERATING,
    ProjectState.VIDEOS_REVIEW,
    ProjectState.VIDEOS_APPROVED,
    ProjectState.FINAL_PREVIEW_READY,
]
STATE_INDEX = {state: index for index, state in enumerate(STATE_ORDER)}
LEGACY_STATE_INDEX = {
    ProjectState.SCRIPT_REVIEW: STATE_INDEX[ProjectState.NARRATION_REVIEW],
    ProjectState.SCRIPT_APPROVED: STATE_INDEX[ProjectState.NARRATION_APPROVED],
    ProjectState.SHOT_PLAN_READY: STATE_INDEX[ProjectState.SHOTS_REVIEW],
    ProjectState.ASSET_PLAN_READY: STATE_INDEX[ProjectState.SHOTS_APPROVED],
    ProjectState.IMAGE_GENERATION: STATE_INDEX[ProjectState.IMAGES_GENERATING],
    ProjectState.IMAGE_REVIEW: STATE_INDEX[ProjectState.IMAGES_REVIEW],
    ProjectState.VIDEO_GENERATION: STATE_INDEX[ProjectState.VIDEOS_GENERATING],
    ProjectState.VIDEO_REVIEW: STATE_INDEX[ProjectState.VIDEOS_REVIEW],
    ProjectState.NARRATION_READY: STATE_INDEX[ProjectState.VOICE_APPROVED],
    ProjectState.PREVIEW_REVIEW: STATE_INDEX[ProjectState.ANIMATIC_READY],
    ProjectState.PICTURE_LOCKED: STATE_INDEX[ProjectState.FINAL_PREVIEW_READY],
}


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
        "story_setup", 1, "Story setup", "Story",
        "Research and structure remain available as preparation without cluttering the production flow.",
        (ProjectState.PROJECT_CREATED, ProjectState.RESEARCH_READY, ProjectState.STRUCTURE_REVIEW, ProjectState.STRUCTURE_APPROVED),
        ("01_research/source_dossier.json", "02_structure/structure.json"),
    ),
    StageDefinition(
        "narration", 2, "Narration", "Narration",
        "Write the documentary for the ear with sparse inline Gemini/ElevenLabs performance tags.",
        (ProjectState.STRUCTURE_APPROVED, ProjectState.NARRATION_REVIEW, ProjectState.NARRATION_APPROVED),
        ("03_narration/narration.json", "03_narration/narration_tagged.txt", "03_narration/narration_clean.txt"),
    ),
    StageDefinition(
        "voice", 3, "Voice", "Voice",
        "Generate, cache and review chapter speech; derive timing from the real assembled voiceover.",
        (ProjectState.NARRATION_APPROVED, ProjectState.VOICE_GENERATING, ProjectState.VOICE_REVIEW, ProjectState.VOICE_APPROVED),
        ("04_voice/audio_manifest.json", "04_voice/voiceover_master.wav", "04_voice/voiceover.mp3", "05_timing/audio_timing.json"),
    ),
    StageDefinition(
        "shots", 4, "Shots", "Shots",
        "Divide the generated audio at word starts and measured pauses, then review image/video prompts.",
        (ProjectState.VOICE_APPROVED, ProjectState.SHOTS_GENERATING, ProjectState.SHOTS_REVIEW, ProjectState.SHOTS_APPROVED),
        ("06_shots/shot_plan.json", "06_shots/shot_plan.md"),
    ),
    StageDefinition(
        "images", 5, "Images", "Images",
        "Generate and approve one primary 16:9 documentary image for every reusable master asset.",
        (ProjectState.SHOTS_APPROVED, ProjectState.IMAGES_GENERATING, ProjectState.IMAGES_REVIEW, ProjectState.IMAGES_APPROVED),
        ("07_images/jobs.json",),
    ),
    StageDefinition(
        "animatic", 6, "Image + sound preview", "Animatic",
        "Review approved images against the actual voiceover and restrained basic ambience before video spend.",
        (ProjectState.IMAGES_APPROVED, ProjectState.ANIMATIC_READY, ProjectState.ANIMATIC_APPROVED),
        ("08_animatic/animatic.mp4", "08_animatic/sound_plan.json", "08_animatic/render_report.json"),
    ),
    StageDefinition(
        "videos", 7, "Video generation", "Videos",
        "Generate 720p 16:9 image-to-video clips only after animatic approval; still-image fallback remains valid.",
        (ProjectState.ANIMATIC_APPROVED, ProjectState.VIDEOS_GENERATING, ProjectState.VIDEOS_REVIEW, ProjectState.VIDEOS_APPROVED),
        ("09_videos/jobs.json",),
    ),
    StageDefinition(
        "final_preview", 8, "Final preview", "Preview",
        "Assemble approved videos, image fallbacks and the master narration into a validated 1080p preview.",
        (ProjectState.VIDEOS_APPROVED, ProjectState.FINAL_PREVIEW_READY),
        ("10_final_preview/final_preview.mp4", "10_final_preview/render_report.json"),
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
                if task_id in current.get("tasks", {}) and isinstance(values, dict):
                    current["tasks"][task_id].update(values)
        if isinstance(payload.get("providers"), dict):
            for provider_id, values in payload["providers"].items():
                if provider_id in current.get("providers", {}) and isinstance(values, dict):
                    current["providers"][provider_id].update(values)
        if isinstance(payload.get("prompt_packs"), dict):
            for pack_id, values in payload["prompt_packs"].items():
                if pack_id in current.get("prompt_packs", {}) and isinstance(values, dict):
                    current["prompt_packs"][pack_id].update(values)
        if isinstance(payload.get("rules"), list):
            current["rules"] = payload["rules"]
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
        }
        config["command_configured"] = bool(config.get("command_template"))
        return config

    def save_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {"agent_mode", "command_template", "default_duration", "default_max_assets", "auto_refresh_seconds", "theme"}
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
        projects = [path.name for path in self.workspace.iterdir() if path.is_dir() and (path / "project_manifest.json").exists()]
        return sorted(projects, key=lambda item: self.store.manifest(item).updated_at, reverse=True)

    def bootstrap(self) -> dict[str, Any]:
        projects = [self.project_summary(project_id) for project_id in self.project_ids()]
        return {
            "projects": projects,
            "totals": {
                "projects": len(projects),
                "in_review": sum(1 for item in projects if "REVIEW" in item["state"]),
                "picture_locked": sum(1 for item in projects if item["state"] == ProjectState.FINAL_PREVIEW_READY.value),
                "assets": sum(int(item["metrics"].get("shots", 0)) for item in projects),
            },
            "config": self.config(),
            "stage_definitions": [self._stage_definition_payload(stage) for stage in STAGES],
            "orchestrator": self.orchestrator(),
        }

    def create_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        tone_value = payload.get("tone", ["investigative", "suspenseful", "respectful"])
        tone = [part.strip() for part in tone_value.split(",") if part.strip()] if isinstance(tone_value, str) else list(tone_value or [])
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
        preview = self._existing_relative(project_id, [
            "10_final_preview/final_preview.mp4",
            "08_animatic/animatic.mp4",
            "07_images/SHOT_001/image.png",
            "06_contact_sheet/contact_sheet.png",
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
            "progress": self.progress_percent(manifest.state),
            "metrics": self.metrics(project_id),
            "next_action": self.next_action(project_id),
            "preview_url": self.artifact_url(project_id, preview) if preview else None,
        }

    def project_detail(self, project_id: str) -> dict[str, Any]:
        brief = self.store.brief(project_id)
        manifest = self.store.manifest(project_id)
        return {
            **self.project_summary(project_id),
            "brief": brief.model_dump(mode="json"),
            "manifest": manifest.model_dump(mode="json"),
            "stages": [self.stage_status(project_id, stage) for stage in STAGES],
            "artifacts": self.artifacts(project_id),
            "approval_summary": self.safe_approval_summary(project_id),
            "manual_requests": self.manual_requests(project_id),
            "contact_sheet_url": self.optional_artifact_url(project_id, "07_images/SHOT_001/image.png"),
            "preview_video_url": self.optional_artifact_url(project_id, "08_animatic/animatic.mp4"),
            "final_video_url": self.optional_artifact_url(project_id, "10_final_preview/final_preview.mp4"),
            "image_factory_zip_url": None,
            "image_factory_packet_ready": False,
            "task_routes": self._project_task_routes(project_id),
            "image_generation_report": self._optional_json(project_id, "07_images/jobs.json"),
            "video_generation_report": self._optional_json(project_id, "09_videos/jobs.json"),
            "voice_manifest": self._optional_json(project_id, "04_voice/audio_manifest.json"),
            "audio_timing": self._optional_json(project_id, "05_timing/audio_timing.json"),
        }

    def metrics(self, project_id: str) -> dict[str, int | float]:
        project = self.store.project_dir(project_id)
        result: dict[str, int | float] = {
            "chapters": 0, "script_words": 0, "shots": 0, "assets": 0,
            "images": 0, "images_approved": 0, "videos": 0, "videos_approved": 0,
            "timeline_entries": 0,
        }
        try:
            result["chapters"] = len(load_model(project / "02_structure/structure.json", DocumentaryStructure).chapters)
        except Exception:
            pass
        try:
            path = project / "03_narration/narration.json"
            if not path.exists():
                path = project / "03_script/script.json"
            result["script_words"] = load_model(path, DocumentaryScript).estimated_word_count
        except Exception:
            pass
        try:
            shots = load_model(project / "06_shots/shot_plan.json", ShotPlan)
            result["shots"] = result["assets"] = len(shots.shots)
            result["timeline_entries"] = len(shots.shots)
        except Exception:
            pass
        for media_type, key in (("image", "images"), ("video", "videos")):
            try:
                manifest = load_model(project / ("07_images/jobs.json" if media_type == "image" else "09_videos/jobs.json"), V1MediaManifest)
                result[key] = sum(1 for item in manifest.jobs if item.status in {"review", "approved"})
                result[f"{key}_approved"] = sum(1 for item in manifest.jobs if item.status == "approved")
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
        for task_id in ("research", "structure", "script", "voice_generator", "shot_planner", "image_generator", "video_generator", "composition_renderer"):
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
        project = self.store.project_dir(project_id)
        summary = {
            "total_assets": 0, "missing_images": [], "pending_image_reviews": [],
            "missing_videos": [], "pending_video_reviews": [], "uncovered_shots": [],
        }
        try:
            shots = load_model(project / "06_shots/shot_plan.json", ShotPlan)
            summary["total_assets"] = len(shots.shots)
            summary["uncovered_shots"] = []
        except Exception:
            return summary
        try:
            images = load_model(project / "07_images/jobs.json", V1MediaManifest)
            summary["missing_images"] = [item.shot_id for item in images.jobs if not item.output or not (project / item.output).exists()]
            summary["pending_image_reviews"] = [item.shot_id for item in images.jobs if item.status != "approved"]
        except Exception:
            summary["missing_images"] = [item.shot_id for item in shots.shots]
        try:
            videos = load_model(project / "09_videos/jobs.json", V1MediaManifest)
            summary["missing_videos"] = [item.shot_id for item in videos.jobs if item.status not in {"approved", "rejected"}]
            summary["pending_video_reviews"] = [item.shot_id for item in videos.jobs if item.status == "review"]
        except Exception:
            pass
        return summary

    def progress_percent(self, state: ProjectState) -> int:
        index = STATE_INDEX.get(state, LEGACY_STATE_INDEX.get(state, 0))
        return min(100, round(index / (len(STATE_ORDER) - 1) * 100))

    def stage_status(self, project_id: str, stage: StageDefinition) -> dict[str, Any]:
        current = self.store.manifest(project_id).state
        indexes = [STATE_INDEX.get(state, LEGACY_STATE_INDEX.get(state, 0)) for state in stage.states]
        current_index = STATE_INDEX.get(current, LEGACY_STATE_INDEX.get(current, 0))
        first, last = min(indexes), max(indexes)
        status = "complete" if current_index > last else "locked" if current_index < first else "active"
        if current in stage.states and ("REVIEW" in current.value or current in {ProjectState.ANIMATIC_READY}):
            status = "review"
        artifacts = []
        project = self.store.project_dir(project_id)
        for relative in stage.artifact_paths:
            path = project / relative
            if path.exists():
                artifacts.append({
                    "name": path.name, "path": relative, "url": self.artifact_url(project_id, relative),
                    "kind": artifact_kind(path), "size": path.stat().st_size,
                })
        return {**self._stage_definition_payload(stage), "status": status, "artifacts": artifacts, "action": self.stage_action(project_id, stage.id)}

    def stage_action(self, project_id: str, stage_id: str) -> dict[str, Any] | None:
        next_action = self.next_action(project_id)
        return next_action if next_action and next_action.get("stage") == stage_id else None

    def next_action(self, project_id: str) -> dict[str, Any] | None:
        state = self.store.manifest(project_id).state
        mapping: dict[ProjectState, dict[str, Any]] = {
            ProjectState.PROJECT_CREATED: action("research", "story_setup", "Build research dossier", "run"),
            ProjectState.RESEARCH_READY: action("structure", "story_setup", "Create story structure", "run"),
            ProjectState.STRUCTURE_REVIEW: action("approve_structure", "story_setup", "Approve structure", "approve"),
            ProjectState.STRUCTURE_APPROVED: action("narration", "narration", "Write tagged narration", "run"),
            ProjectState.NARRATION_REVIEW: action("approve_narration", "narration", "Approve narration", "approve"),
            ProjectState.NARRATION_APPROVED: action("generate_voice", "voice", "Generate documentary voice", "run"),
            ProjectState.VOICE_REVIEW: action("approve_voice", "voice", "Approve generated voice", "approve"),
            ProjectState.VOICE_APPROVED: action("generate_timing", "voice", "Align the real voiceover", "run"),
            ProjectState.SHOTS_GENERATING: action("shots", "shots", "Plan exact audio-led shots", "run"),
            ProjectState.SHOTS_REVIEW: action("approve_shots", "shots", "Approve shot divisions", "approve"),
            ProjectState.SHOTS_APPROVED: action("prepare_images", "images", "Prepare image jobs", "run"),
            ProjectState.IMAGES_GENERATING: action("generate_images", "images", "Generate shot images", "run"),
            ProjectState.IMAGES_REVIEW: action("approve_images", "images", "Approve shot images", "approve"),
            ProjectState.IMAGES_APPROVED: action("render_animatic", "animatic", "Render image + sound preview", "render"),
            ProjectState.ANIMATIC_READY: action("approve_animatic", "animatic", "Approve animatic", "approve"),
            ProjectState.ANIMATIC_APPROVED: action("prepare_videos", "videos", "Prepare 720p video jobs", "run"),
            ProjectState.VIDEOS_GENERATING: action("generate_videos", "videos", "Generate approved video shots", "run"),
            ProjectState.VIDEOS_REVIEW: action("approve_videos", "videos", "Approve generated videos", "approve"),
            ProjectState.VIDEOS_APPROVED: action("render_final_preview", "final_preview", "Render final 1080p preview", "render"),
        }
        if state == ProjectState.VOICE_APPROVED and (self.store.project_dir(project_id) / "05_timing/audio_timing.json").exists():
            return action("shots", "shots", "Plan exact audio-led shots", "run")
        return mapping.get(state)

    def assets(self, project_id: str) -> dict[str, Any]:
        project = self.store.project_dir(project_id)
        shot_path = project / "06_shots/shot_plan.json"
        if not shot_path.exists():
            return {"assets": [], "summary": self.safe_approval_summary(project_id)}
        shots = load_model(shot_path, ShotPlan)
        images = self._optional_json(project_id, "07_images/jobs.json") or {"jobs": []}
        videos = self._optional_json(project_id, "09_videos/jobs.json") or {"jobs": []}
        image_by_id = {item["shot_id"]: item for item in images.get("jobs", [])}
        video_by_id = {item["shot_id"]: item for item in videos.get("jobs", [])}
        assets = []
        for shot in shots.shots:
            image = image_by_id.get(shot.shot_id, {})
            video = video_by_id.get(shot.shot_id, {})
            assets.append({
                "asset_id": shot.shot_id,
                "title": shot.narration_text[:80],
                "linked_shots": [shot.shot_id],
                "image_prompt": shot.image_prompt,
                "video_prompt": shot.video_prompt,
                "approved_image": image.get("output") if image.get("status") == "approved" else None,
                "approved_video": video.get("output") if video.get("status") == "approved" else None,
                "image_review": {"status": image.get("status", "pending")},
                "video_review": {"status": video.get("status", "pending")},
                "image_url": self.artifact_url(project_id, image["output"]) if image.get("output") and (project / image["output"]).exists() else None,
                "video_url": self.artifact_url(project_id, video["output"]) if video.get("output") and (project / video["output"]).exists() else None,
                "shots": [shot.model_dump(mode="json")],
            })
        return {"assets": assets, "summary": self.safe_approval_summary(project_id), "maximum_assets": len(assets)}

    def timeline(self, project_id: str) -> dict[str, Any]:
        project = self.store.project_dir(project_id)
        path = project / "06_shots/shot_plan.json"
        if not path.exists():
            return {"entries": [], "total_seconds": 0}
        shots = load_model(path, ShotPlan)
        images = self._optional_json(project_id, "07_images/jobs.json") or {"jobs": []}
        videos = self._optional_json(project_id, "09_videos/jobs.json") or {"jobs": []}
        image_by_id = {item["shot_id"]: item for item in images.get("jobs", [])}
        video_by_id = {item["shot_id"]: item for item in videos.get("jobs", [])}
        entries = []
        for shot in shots.shots:
            video = video_by_id.get(shot.shot_id, {})
            image = image_by_id.get(shot.shot_id, {})
            if video.get("status") == "approved" and video.get("output"):
                source, kind = video["output"], "video"
            elif image.get("status") == "approved" and image.get("output"):
                source, kind = image["output"], "image"
            else:
                source, kind = "", "placeholder"
            entries.append({
                "timeline_id": f"TL_{len(entries) + 1:03d}",
                "shot_id": shot.shot_id,
                "start": shot.start,
                "end": shot.end,
                "narration_ids": shot.narration_ids,
                "source_media": source,
                "media_kind": kind,
                "source_url": self.artifact_url(project_id, source) if source else None,
            })
        return {"project_id": shots.project_id, "entries": entries, "total_seconds": shots.total_seconds}

    def artifacts(self, project_id: str) -> list[dict[str, Any]]:
        project = self.store.project_dir(project_id)
        results: list[dict[str, Any]] = []
        allowed_suffixes = {".json", ".md", ".txt", ".png", ".jpg", ".jpeg", ".webp", ".pdf", ".html", ".mp4", ".wav", ".mp3", ".zip"}
        for path in project.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in allowed_suffixes:
                continue
            relative = path.relative_to(project).as_posix()
            if "/_render/" in f"/{relative}/" or relative.startswith("_requests/") and path.name.endswith("_schema.json"):
                continue
            results.append({
                "name": path.name, "path": relative, "stage": relative.split("/", 1)[0],
                "kind": artifact_kind(path), "size": path.stat().st_size,
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
        aliases = {"script": "script", "narration": "script", "research": "research", "structure": "structure"}
        if stage not in aliases:
            raise ValueError("manual response stage must be research, structure, narration, or script")
        request_dir = self.store.project_dir(project_id) / "_requests"
        prompt_stage = aliases[stage]
        if not (request_dir / f"{prompt_stage}_prompt.md").exists():
            raise FileNotFoundError(f"no pending manual request for {stage}")
        path = request_dir / f"{prompt_stage}_response.json"
        write_json(path, value)
        return path

    def artifact_url(self, project_id: str, relative: str) -> str:
        return "/artifacts/" + quote(project_id) + "/" + "/".join(quote(part) for part in relative.split("/"))

    def optional_artifact_url(self, project_id: str, relative: str) -> str | None:
        return self.artifact_url(project_id, relative) if (self.store.project_dir(project_id) / relative).exists() else None

    def _existing_relative(self, project_id: str, candidates: list[str]) -> str | None:
        project = self.store.project_dir(project_id)
        return next((relative for relative in candidates if (project / relative).exists()), None)

    @staticmethod
    def _stage_definition_payload(stage: StageDefinition) -> dict[str, Any]:
        return {
            "id": stage.id, "number": stage.number, "title": stage.title,
            "short_title": stage.short_title, "description": stage.description,
        }


def action(action_id: str, stage: str, label: str, kind: str) -> dict[str, Any]:
    return {"id": action_id, "stage": stage, "label": label, "kind": kind}


def state_label(state: ProjectState) -> str:
    return state.value.replace("_", " ").title()


def artifact_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return "image"
    if suffix in {".mp4", ".mov", ".webm"}:
        return "video"
    if suffix in {".wav", ".mp3", ".m4a"}:
        return "audio"
    if suffix == ".json":
        return "json"
    if suffix in {".md", ".txt"}:
        return "text"
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".zip":
        return "archive"
    return "file"
