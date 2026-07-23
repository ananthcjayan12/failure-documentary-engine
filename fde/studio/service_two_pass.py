from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from ..io import load_model, read_json
from ..models import (
    EditorialShotPlan,
    MasterAssetPlan,
    MasterFootageStrategy,
    ProjectBrief,
    ProjectState,
    ShotSkeletonPlan,
    Timeline,
    V1MediaManifest,
)
from ..timeline import build_timeline
from . import service as _base


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
    ProjectState.SHOT_SKELETON_GENERATING,
    ProjectState.SHOT_SKELETON_REVIEW,
    ProjectState.SHOT_SKELETON_APPROVED,
    ProjectState.MASTER_PLAN_GENERATING,
    ProjectState.MASTER_PLAN_REVIEW,
    ProjectState.MASTER_PLAN_APPROVED,
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

STAGES = [
    _base.StageDefinition(
        "story_setup", 1, "Story setup", "Story",
        "Research and structure remain the evidence and narrative foundation.",
        (ProjectState.PROJECT_CREATED, ProjectState.RESEARCH_READY, ProjectState.STRUCTURE_REVIEW, ProjectState.STRUCTURE_APPROVED),
        ("01_research/source_dossier.json", "02_structure/structure.json"),
    ),
    _base.StageDefinition(
        "narration", 2, "Narration", "Narration",
        "Write and approve expressive evidence-grounded narration.",
        (ProjectState.STRUCTURE_APPROVED, ProjectState.NARRATION_REVIEW, ProjectState.NARRATION_APPROVED),
        ("03_narration/narration.json", "03_narration/narration_tagged.txt"),
    ),
    _base.StageDefinition(
        "voice", 3, "Voice and alignment", "Voice",
        "Generate the master voice and exact word timing that owns the edit.",
        (ProjectState.NARRATION_APPROVED, ProjectState.VOICE_GENERATING, ProjectState.VOICE_REVIEW, ProjectState.VOICE_APPROVED),
        ("04_voice/audio_manifest.json", "04_voice/voiceover_master.wav", "05_timing/audio_timing.json"),
    ),
    _base.StageDefinition(
        "shot_skeleton", 4, "Audio-led shot skeleton", "Skeleton",
        "Compile immutable timing, narration membership, claim scope, and broad visual purpose without media prompts.",
        (ProjectState.VOICE_APPROVED, ProjectState.SHOT_SKELETON_GENERATING, ProjectState.SHOT_SKELETON_REVIEW, ProjectState.SHOT_SKELETON_APPROVED),
        ("06_shots/shot_skeleton.json", "06_shots/shot_skeleton.md"),
    ),
    _base.StageDefinition(
        "master_footage", 5, "24-package master-footage plan", "Master plan",
        "Review exactly 8 hero, 8 loopable atmosphere, and 8 investigation packages before generation.",
        (ProjectState.SHOT_SKELETON_APPROVED, ProjectState.MASTER_PLAN_GENERATING, ProjectState.MASTER_PLAN_REVIEW, ProjectState.MASTER_PLAN_APPROVED),
        ("05_master_assets/master_footage_plan.json", "05_master_assets/validation_report.json", "05_master_assets/approved_master_footage_plan.json"),
    ),
    _base.StageDefinition(
        "shots", 6, "Editorial shot direction", "Edit plan",
        "Assign approved packages, crops, loops, freezes, callbacks, and typed overlays to immutable shots.",
        (ProjectState.MASTER_PLAN_APPROVED, ProjectState.SHOTS_GENERATING, ProjectState.SHOTS_REVIEW, ProjectState.SHOTS_APPROVED),
        ("06_shots/editorial_shot_plan.json",),
    ),
    _base.StageDefinition(
        "images", 7, "Master-package images", "Images",
        "Generate and approve exactly one image for each of the 24 packages.",
        (ProjectState.SHOTS_APPROVED, ProjectState.IMAGES_GENERATING, ProjectState.IMAGES_REVIEW, ProjectState.IMAGES_APPROVED),
        ("07_images/jobs.json", "05_master_assets/generation_plan.json"),
    ),
    _base.StageDefinition(
        "animatic", 8, "Editorial image + sound preview", "Animatic",
        "Review package reuse, crop, loop, freeze, coded overlays, voice, and basic sound before video spend.",
        (ProjectState.IMAGES_APPROVED, ProjectState.ANIMATIC_READY, ProjectState.ANIMATIC_APPROVED),
        ("08_animatic/animatic.mp4", "08_animatic/render_report.json", "12_timeline/timeline.json"),
    ),
    _base.StageDefinition(
        "videos", 9, "Master-package videos", "Videos",
        "Generate exactly one configured-duration source video for each package; coded graphics create no provider job.",
        (ProjectState.ANIMATIC_APPROVED, ProjectState.VIDEOS_GENERATING, ProjectState.VIDEOS_REVIEW, ProjectState.VIDEOS_APPROVED),
        ("09_videos/jobs.json",),
    ),
    _base.StageDefinition(
        "final_preview", 10, "Final preview", "Preview",
        "Render the exact voice-led timeline using package playback semantics and deterministic overlays.",
        (ProjectState.VIDEOS_APPROVED, ProjectState.FINAL_PREVIEW_READY),
        ("10_final_preview/final_preview.mp4", "10_final_preview/render_report.json"),
    ),
]

_base.STATE_ORDER[:] = STATE_ORDER
_base.STATE_INDEX.clear()
_base.STATE_INDEX.update({state: index for index, state in enumerate(STATE_ORDER)})
_base.STAGES[:] = STAGES
_base.DEFAULT_CONFIG["default_max_assets"] = 24


class TwoPassStudioService(_base.StudioService):
    def create_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        tone_value = payload.get("tone", ["investigative", "suspenseful", "respectful"])
        tone = [part.strip() for part in tone_value.split(",") if part.strip()] if isinstance(tone_value, str) else list(tone_value or [])
        strategy_payload = payload.get("master_footage_strategy") or {}
        strategy = MasterFootageStrategy(
            hero_count=int(strategy_payload.get("hero_count", payload.get("hero_count", 8))),
            atmosphere_count=int(strategy_payload.get("atmosphere_count", payload.get("atmosphere_count", 8))),
            investigation_count=int(strategy_payload.get("investigation_count", payload.get("investigation_count", 8))),
            source_video_duration_seconds=float(strategy_payload.get("source_video_duration_seconds", payload.get("master_video_duration_seconds", 5))),
            enforce_exact_counts=bool(strategy_payload.get("enforce_exact_counts", True)),
            target_generated_video_count=int(strategy_payload.get("target_generated_video_count", 24)),
        )
        brief = ProjectBrief(
            project_id=str(payload.get("project_id", "")).strip(),
            title=str(payload.get("title", "")).strip() or "Untitled Failure Investigation",
            topic=str(payload.get("topic", "")).strip() or str(payload.get("title", "")).strip(),
            target_duration_seconds=float(payload.get("target_duration_seconds", 480)),
            maximum_master_assets=int(payload.get("maximum_master_assets", 24)),
            master_video_duration_seconds=strategy.source_video_duration_seconds,
            master_footage_strategy=strategy,
            language=str(payload.get("language", "English")),
            audience=str(payload.get("audience", "General international audience")),
            tone=tone or ["investigative", "suspenseful", "respectful"],
        )
        self.store.create(brief)
        return self.project_detail(brief.project_id)

    def progress_percent(self, state: ProjectState) -> int:
        legacy = _base.LEGACY_STATE_INDEX.get(state, 0)
        index = _base.STATE_INDEX.get(state, legacy)
        return min(100, round(index / (len(STATE_ORDER) - 1) * 100))

    def next_action(self, project_id: str) -> dict[str, Any] | None:
        state = self.store.manifest(project_id).state
        mapping = {
            ProjectState.PROJECT_CREATED: _base.action("research", "story_setup", "Build research dossier", "run"),
            ProjectState.RESEARCH_READY: _base.action("structure", "story_setup", "Create story structure", "run"),
            ProjectState.STRUCTURE_REVIEW: _base.action("approve_structure", "story_setup", "Approve structure", "approve"),
            ProjectState.STRUCTURE_APPROVED: _base.action("narration", "narration", "Write tagged narration", "run"),
            ProjectState.NARRATION_REVIEW: _base.action("approve_narration", "narration", "Approve narration", "approve"),
            ProjectState.NARRATION_APPROVED: _base.action("generate_voice", "voice", "Generate documentary voice", "run"),
            ProjectState.VOICE_REVIEW: _base.action("approve_voice", "voice", "Approve generated voice", "approve"),
            ProjectState.VOICE_APPROVED: _base.action("generate_timing", "voice", "Align current voiceover", "run"),
            ProjectState.SHOT_SKELETON_GENERATING: _base.action("shot_skeleton", "shot_skeleton", "Compile audio-led skeleton", "run"),
            ProjectState.SHOT_SKELETON_REVIEW: _base.action("approve_shot_skeleton", "shot_skeleton", "Approve immutable shot skeleton", "approve"),
            ProjectState.SHOT_SKELETON_APPROVED: _base.action("master_footage", "master_footage", "Design the 24 footage packages", "run"),
            ProjectState.MASTER_PLAN_REVIEW: _base.action("approve_master_footage", "master_footage", "Approve the 8 / 8 / 8 master plan", "approve"),
            ProjectState.MASTER_PLAN_APPROVED: _base.action("editorial_shots", "shots", "Direct shots from approved packages", "run"),
            ProjectState.SHOTS_REVIEW: _base.action("approve_shots", "shots", "Approve editorial shot plan", "approve"),
            ProjectState.SHOTS_APPROVED: _base.action("prepare_images", "images", "Prepare 24 image jobs", "run"),
            ProjectState.IMAGES_GENERATING: _base.action("generate_images", "images", "Generate package images", "run"),
            ProjectState.IMAGES_REVIEW: _base.action("approve_images", "images", "Approve package images", "approve"),
            ProjectState.IMAGES_APPROVED: _base.action("render_animatic", "animatic", "Render editorial animatic", "render"),
            ProjectState.ANIMATIC_READY: _base.action("approve_animatic", "animatic", "Approve animatic", "approve"),
            ProjectState.ANIMATIC_APPROVED: _base.action("prepare_videos", "videos", "Prepare 24 video jobs", "run"),
            ProjectState.VIDEOS_GENERATING: _base.action("generate_videos", "videos", "Generate package videos", "run"),
            ProjectState.VIDEOS_REVIEW: _base.action("approve_videos", "videos", "Approve package videos", "approve"),
            ProjectState.VIDEOS_APPROVED: _base.action("render_final_preview", "final_preview", "Render final preview", "render"),
        }
        project = self.store.project_dir(project_id)
        if state == ProjectState.VOICE_APPROVED and (project / "05_timing/audio_timing.json").exists():
            return _base.action("shot_skeleton", "shot_skeleton", "Compile audio-led skeleton", "run")
        return mapping.get(state)

    def metrics(self, project_id: str) -> dict[str, int | float]:
        result = super().metrics(project_id)
        project = self.store.project_dir(project_id)
        try:
            skeleton = load_model(project / "06_shots/shot_skeleton.json", ShotSkeletonPlan)
            result["shots"] = len(skeleton.shots)
            result["timeline_entries"] = len(skeleton.shots)
        except Exception:
            pass
        try:
            path = project / "05_master_assets/approved_master_footage_plan.json"
            if not path.exists():
                path = project / "05_master_assets/master_footage_plan.json"
            master = load_model(path, MasterAssetPlan)
            result["assets"] = len(master.assets)
            counts = Counter(item.category for item in master.assets)
            result["hero_assets"] = counts.get("hero", 0)
            result["atmosphere_assets"] = counts.get("atmosphere", 0)
            result["investigation_assets"] = counts.get("investigation", 0)
        except Exception:
            pass
        return result

    def _project_task_routes(self, project_id: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for task_id in (
            "research", "structure", "narration_writer", "voice_generator", "word_alignment",
            "master_footage_planner", "editorial_director", "image_generator",
            "animatic_renderer", "video_generator", "final_renderer",
        ):
            try:
                route = self._resolved_route(project_id, task_id)
                result[task_id] = {
                    "provider": route.get("provider"), "provider_label": route.get("provider_label"),
                    "provider_mode": route.get("provider_mode"), "model": route.get("model"),
                    "capability": route.get("capability"), "resolution": route.get("resolution"),
                    "quality": route.get("quality"), "duration_seconds": route.get("duration_seconds"),
                }
            except Exception as exc:
                result[task_id] = {"error": str(exc)}
        return result

    def project_detail(self, project_id: str) -> dict[str, Any]:
        payload = super().project_detail(project_id)
        payload["master_footage_plan"] = self._optional_json(project_id, "05_master_assets/approved_master_footage_plan.json") or self._optional_json(project_id, "05_master_assets/master_footage_plan.json")
        payload["editorial_shot_plan"] = self._optional_json(project_id, "06_shots/editorial_shot_plan.json")
        payload["shot_skeleton"] = self._optional_json(project_id, "06_shots/shot_skeleton.json")
        return payload

    def assets(self, project_id: str) -> dict[str, Any]:
        project = self.store.project_dir(project_id)
        path = project / "05_master_assets/approved_master_footage_plan.json"
        if not path.exists():
            path = project / "05_master_assets/master_footage_plan.json"
        if not path.exists():
            return {"assets": [], "summary": self.safe_approval_summary(project_id), "category_counts": {}}
        plan = load_model(path, MasterAssetPlan)
        images = self._optional_json(project_id, "07_images/jobs.json") or {"jobs": []}
        videos = self._optional_json(project_id, "09_videos/jobs.json") or {"jobs": []}
        image_by_id = {(item.get("asset_id") or item.get("shot_id")): item for item in images.get("jobs", [])}
        video_by_id = {(item.get("asset_id") or item.get("shot_id")): item for item in videos.get("jobs", [])}
        editorial = self._optional_json(project_id, "06_shots/editorial_shot_plan.json") or {"shots": []}
        shots_by_asset: dict[str, list[dict[str, Any]]] = {}
        for shot in editorial.get("shots", []):
            if shot.get("master_asset_id"):
                shots_by_asset.setdefault(shot["master_asset_id"], []).append(shot)
        assets = []
        for asset in plan.assets:
            image = image_by_id.get(asset.asset_id, {})
            video = video_by_id.get(asset.asset_id, {})
            predicted = sum(float(item.get("duration", 0)) for item in shots_by_asset.get(asset.asset_id, []))
            assets.append({
                **asset.model_dump(mode="json"),
                "predicted_timeline_coverage_seconds": round(predicted, 3),
                "image_review": {"status": image.get("status", "pending")},
                "video_review": {"status": video.get("status", "pending")},
                "image_url": self.artifact_url(project_id, image["output"]) if image.get("output") and (project / image["output"]).exists() else None,
                "video_url": self.artifact_url(project_id, video["output"]) if video.get("output") and (project / video["output"]).exists() else None,
                "shots": shots_by_asset.get(asset.asset_id, []),
            })
        return {
            "assets": assets,
            "summary": self.safe_approval_summary(project_id),
            "maximum_assets": plan.maximum_assets,
            "category_counts": dict(Counter(item.category for item in plan.assets)),
            "uncovered_shots": plan.uncovered_shots,
            "continuity_conflicts": plan.continuity_conflicts,
            "master_plan_version": plan.plan_version,
            "master_plan_status": plan.status,
        }

    def timeline(self, project_id: str) -> dict[str, Any]:
        project = self.store.project_dir(project_id)
        path = project / "12_timeline/timeline.json"
        if not path.exists() and (project / "06_shots/editorial_shot_plan.json").exists():
            try:
                build_timeline(project)
            except Exception:
                return {"entries": [], "total_seconds": 0, "overlay_tracks": {}}
        if path.exists():
            return read_json(path)
        return {"entries": [], "total_seconds": 0, "overlay_tracks": {}}


# Patch the class imported by server.py.
_base.StudioService = TwoPassStudioService
StudioService = TwoPassStudioService
