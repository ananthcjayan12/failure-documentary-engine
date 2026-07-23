from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectState(str, Enum):
    PROJECT_CREATED = "PROJECT_CREATED"
    RESEARCH_READY = "RESEARCH_READY"
    STRUCTURE_REVIEW = "STRUCTURE_REVIEW"
    STRUCTURE_APPROVED = "STRUCTURE_APPROVED"

    NARRATION_REVIEW = "NARRATION_REVIEW"
    NARRATION_APPROVED = "NARRATION_APPROVED"
    VOICE_GENERATING = "VOICE_GENERATING"
    VOICE_REVIEW = "VOICE_REVIEW"
    VOICE_APPROVED = "VOICE_APPROVED"

    SHOT_SKELETON_GENERATING = "SHOT_SKELETON_GENERATING"
    SHOT_SKELETON_REVIEW = "SHOT_SKELETON_REVIEW"
    SHOT_SKELETON_APPROVED = "SHOT_SKELETON_APPROVED"
    MASTER_PLAN_GENERATING = "MASTER_PLAN_GENERATING"
    MASTER_PLAN_REVIEW = "MASTER_PLAN_REVIEW"
    MASTER_PLAN_APPROVED = "MASTER_PLAN_APPROVED"

    SHOTS_GENERATING = "SHOTS_GENERATING"
    SHOTS_REVIEW = "SHOTS_REVIEW"
    SHOTS_APPROVED = "SHOTS_APPROVED"
    IMAGES_GENERATING = "IMAGES_GENERATING"
    IMAGES_REVIEW = "IMAGES_REVIEW"
    IMAGES_APPROVED = "IMAGES_APPROVED"
    ANIMATIC_READY = "ANIMATIC_READY"
    ANIMATIC_APPROVED = "ANIMATIC_APPROVED"
    VIDEOS_GENERATING = "VIDEOS_GENERATING"
    VIDEOS_REVIEW = "VIDEOS_REVIEW"
    VIDEOS_APPROVED = "VIDEOS_APPROVED"
    FINAL_PREVIEW_READY = "FINAL_PREVIEW_READY"

    # Backwards-compatible states retained for existing projects and commands.
    SCRIPT_REVIEW = "SCRIPT_REVIEW"
    SCRIPT_APPROVED = "SCRIPT_APPROVED"
    SHOT_PLAN_READY = "SHOT_PLAN_READY"
    ASSET_PLAN_READY = "ASSET_PLAN_READY"
    IMAGE_GENERATION = "IMAGE_GENERATION"
    IMAGE_REVIEW = "IMAGE_REVIEW"
    VIDEO_GENERATION = "VIDEO_GENERATION"
    VIDEO_REVIEW = "VIDEO_REVIEW"
    NARRATION_READY = "NARRATION_READY"
    PREVIEW_REVIEW = "PREVIEW_REVIEW"
    PICTURE_LOCKED = "PICTURE_LOCKED"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    CHANGE_REQUESTED = "change_requested"
    REJECTED = "rejected"


class MasterFootageStrategy(BaseModel):
    hero_count: int = Field(default=8, ge=0, le=60)
    atmosphere_count: int = Field(default=8, ge=0, le=60)
    investigation_count: int = Field(default=8, ge=0, le=60)
    source_video_duration_seconds: float = Field(default=5, ge=1, le=30)
    enforce_exact_counts: bool = True
    target_generated_video_count: int = Field(default=24, ge=1, le=60)

    @property
    def category_total(self) -> int:
        return self.hero_count + self.atmosphere_count + self.investigation_count

    @model_validator(mode="after")
    def validate_total(self) -> "MasterFootageStrategy":
        if self.enforce_exact_counts and self.category_total != self.target_generated_video_count:
            raise ValueError(
                "hero_count + atmosphere_count + investigation_count must equal "
                "target_generated_video_count when exact counts are enforced"
            )
        return self


class ProjectBrief(BaseModel):
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    title: str
    topic: str
    target_duration_seconds: float = Field(default=480, gt=30)
    tone: list[str] = Field(default_factory=lambda: ["investigative", "suspenseful", "respectful"])
    maximum_master_assets: int = Field(default=24, ge=1, le=60)
    master_video_duration_seconds: float = Field(default=5, ge=1, le=30)
    master_footage_strategy: MasterFootageStrategy = Field(default_factory=MasterFootageStrategy)
    language: str = "English"
    audience: str = "General international audience"
    created_at: str = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def synchronize_legacy_duration(self) -> "ProjectBrief":
        if "master_footage_strategy" not in self.model_fields_set:
            self.master_footage_strategy.source_video_duration_seconds = self.master_video_duration_seconds
        return self


class ProjectManifest(BaseModel):
    project_id: str
    state: ProjectState = ProjectState.PROJECT_CREATED
    current_versions: dict[str, int] = Field(default_factory=dict)
    approved_versions: dict[str, int] = Field(default_factory=dict)
    invalidated_targets: list[str] = Field(default_factory=list)
    updated_at: str = Field(default_factory=utc_now)


class SourceRef(BaseModel):
    source_id: str
    title: str
    url: str | None = None
    publisher: str | None = None
    published_date: str | None = None
    source_type: str = "unknown"
    notes: str = ""


class Claim(BaseModel):
    claim_id: str
    statement: str
    status: Literal["confirmed", "probable", "disputed", "theory", "unknown"]
    source_ids: list[str] = Field(default_factory=list)
    allowed_language: str = ""
    prohibited_language: str = ""


class ResearchDossier(BaseModel):
    project_id: str
    summary: str
    timeline: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    disputed_claims: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)


class Chapter(BaseModel):
    chapter_id: str
    title: str
    start_target: float
    end_target: float
    narrative_purpose: str
    opening_question: str = ""
    key_information: list[str] = Field(default_factory=list)
    reveal: str = ""
    ending_hook: str = ""

    @model_validator(mode="after")
    def validate_time(self) -> "Chapter":
        if self.end_target <= self.start_target:
            raise ValueError("chapter end_target must be after start_target")
        return self


class DocumentaryStructure(BaseModel):
    project_id: str
    title: str
    chapters: list[Chapter]
    total_target_seconds: float


class NarrationSegment(BaseModel):
    narration_id: str
    chapter_id: str
    text: str
    estimated_start: float = 0
    estimated_duration: float = Field(default=1, gt=0)
    mood: str = "investigative"
    intensity: float = Field(default=0.5, ge=0, le=1)
    claim_ids: list[str] = Field(default_factory=list)
    pause_after_seconds: float = Field(default=0, ge=0)


class DocumentaryScript(BaseModel):
    project_id: str
    title: str
    segments: list[NarrationSegment]
    estimated_total_seconds: float = 0
    estimated_word_count: int = 0
    tts_narration: str = ""

    @model_validator(mode="after")
    def fill_summary_fields(self) -> "DocumentaryScript":
        if not self.tts_narration:
            self.tts_narration = "\n\n".join(item.text.strip() for item in self.segments)
        if not self.estimated_word_count:
            import re
            clean = re.sub(r"\[[^\[\]]+\]\s*", "", self.tts_narration)
            self.estimated_word_count = len(clean.split())
        if not self.estimated_total_seconds:
            self.estimated_total_seconds = sum(item.estimated_duration for item in self.segments)
        return self


class Shot(BaseModel):
    """Legacy shot contract retained for old projects and compatibility mirrors."""

    shot_id: str
    chapter_id: str = ""
    narration_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    start: float
    duration: float = Field(default=1, gt=0)
    end: float | None = None
    narration_text: str = ""
    visual_purpose: str = ""
    story_function: str = "support"
    factual_scope: list[str] = Field(default_factory=list)
    visual_type: str = "unassigned"
    suggested_visual: str = ""
    image_prompt: str = ""
    video_prompt: str = ""
    sound_hint: str = ""
    transition: str = "hard_cut"
    camera: str = ""
    motion: str = ""
    overlay_requirements: list[str] = Field(default_factory=list)
    suspense_function: str = "support"
    requires_new_master_asset: bool = False
    candidate_master_asset: str | None = None

    @model_validator(mode="after")
    def normalize_end(self) -> "Shot":
        if self.end is None:
            self.end = self.start + self.duration
        elif self.end <= self.start:
            raise ValueError("shot end must be after start")
        else:
            self.duration = self.end - self.start
        return self


class ShotPlan(BaseModel):
    """Legacy shot-plan container retained for old JSON and reports."""

    project_id: str
    shots: list[Shot]
    total_seconds: float
    voiceover_sha256: str = ""


class ShotSkeleton(BaseModel):
    shot_id: str
    chapter_id: str = ""
    narration_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    start: float
    end: float
    duration: float = Field(gt=0)
    narration_text: str = ""
    visual_purpose: str = ""
    story_function: str = "support"
    factual_scope: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_timing(self) -> "ShotSkeleton":
        if self.end <= self.start:
            raise ValueError("shot skeleton end must be after start")
        expected = self.end - self.start
        if abs(self.duration - expected) > 0.01:
            self.duration = expected
        return self


class ShotSkeletonPlan(BaseModel):
    project_id: str
    shots: list[ShotSkeleton]
    total_seconds: float
    voiceover_sha256: str
    timing_source: str = "audio_word_alignment"


class AudioChapterRecord(BaseModel):
    paragraph_id: str
    tagged_text: str
    clean_text: str
    path: str
    cache_key: str
    cache_reused: bool = False
    absolute_start: float
    speech_duration: float
    trailing_pause: float
    absolute_end: float
    quality: dict[str, float | str] = Field(default_factory=dict)
    alignment_path: str | None = None


class AudioManifest(BaseModel):
    project_id: str
    provider: str
    model_id: str
    voice_id: str
    sample_rate: int = 24000
    chapter_gap_seconds: float = 0.3
    duration_seconds: float
    voiceover_wav: str
    voiceover_mp3: str | None = None
    voiceover_sha256: str
    chapters: list[AudioChapterRecord]
    created_at: str = Field(default_factory=utc_now)


class WordTiming(BaseModel):
    index: int
    paragraph_id: str
    word: str
    start: float
    end: float
    confidence: float | None = None


class ParagraphTiming(BaseModel):
    paragraph_id: str
    start: float
    end: float
    duration: float


class AudioTiming(BaseModel):
    project_id: str
    source: str
    exact: bool
    voiceover_sha256: str
    audio_duration_seconds: float
    paragraphs: list[ParagraphTiming]
    words: list[WordTiming]


class CropRegion(BaseModel):
    crop_id: str
    description: str
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    width: float | None = Field(default=None, gt=0, le=1)
    height: float | None = Field(default=None, gt=0, le=1)


class DisclosureLabel(BaseModel):
    text: str = "RECONSTRUCTION"
    required: bool = False


class OverlaySpec(BaseModel):
    type: str
    template_id: str
    data_source: str = "approved_claims"
    claim_ids: list[str] = Field(default_factory=list)
    elements: list[str] = Field(default_factory=list)
    safe_zone: str = "upper_right"
    disclosure: DisclosureLabel | None = None


class CoverageAssignment(BaseModel):
    shot_id: str
    mode: Literal["coded_graphic", "archive_media", "generated_still", "black_or_negative_space"]
    reason: str
    archive_source: str | None = None
    overlay: OverlaySpec | None = None


class AssetReview(BaseModel):
    status: ReviewStatus = ReviewStatus.PENDING
    instruction: str = ""
    preserve: list[str] = Field(default_factory=list)
    reviewer: str = "manual-reviewer"
    reviewed_at: str = Field(default_factory=utc_now)


class MasterAsset(BaseModel):
    asset_id: str
    title: str
    category: Literal["hero", "atmosphere", "investigation", "story_specific"]
    linked_shots: list[str]
    primary_use: str
    secondary_uses: list[str] = Field(default_factory=list)
    required_reuse_count: int = Field(default=1, ge=1)
    factual_scope: list[str] = Field(default_factory=list)
    factual_context_id: str = ""
    source_duration_seconds: float = Field(default=5, ge=1, le=30)
    loopable: bool = False
    maximum_continuous_use_seconds: float = Field(default=10, ge=1, le=120)
    allowed_operations: list[str] = Field(default_factory=lambda: ["full_frame", "crop", "freeze"])
    crop_regions: list[CropRegion] = Field(default_factory=list)
    overlay_safe_zones: list[str] = Field(default_factory=lambda: ["upper_right"])
    continuity_requirements: list[str] = Field(default_factory=list)
    prohibited_details: list[str] = Field(default_factory=lambda: ["embedded text"])
    camera_stationary: bool = False
    seamless_loop_required: bool = False
    subject_identity_requirements: list[str] = Field(default_factory=list)
    subject_geometry_requirements: list[str] = Field(default_factory=list)
    reconstruction_disclosure: DisclosureLabel | None = None
    playback_speed_min: float = Field(default=0.5, gt=0, le=4)
    playback_speed_max: float = Field(default=1.25, gt=0, le=4)
    supported_overlay_families: list[str] = Field(default_factory=list)
    opening_frame_stable: bool = True
    ending_frame_stable: bool = True
    major_story_moment: bool = False
    reuse_rationale: str = ""
    image_prompt: str = ""
    video_prompt: str = ""
    image_version: int = 0
    video_version: int = 0
    approved_image: str | None = None
    approved_video: str | None = None
    image_review: AssetReview = Field(default_factory=AssetReview)
    video_review: AssetReview = Field(default_factory=AssetReview)

    @model_validator(mode="after")
    def validate_speed_range(self) -> "MasterAsset":
        if self.playback_speed_max < self.playback_speed_min:
            raise ValueError("playback_speed_max must be greater than or equal to playback_speed_min")
        return self


class MasterAssetPlan(BaseModel):
    project_id: str
    maximum_assets: int
    strategy: MasterFootageStrategy = Field(default_factory=MasterFootageStrategy)
    plan_version: int = 0
    status: Literal["proposal", "approved", "legacy"] = "proposal"
    assets: list[MasterAsset]
    non_generated_coverage: list[CoverageAssignment] = Field(default_factory=list)
    uncovered_shots: list[str] = Field(default_factory=list)
    continuity_conflicts: list[str] = Field(default_factory=list)
    migration_notes: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def enforce_limit(self) -> "MasterAssetPlan":
        if len(self.assets) > self.maximum_assets:
            raise ValueError(f"asset count {len(self.assets)} exceeds maximum {self.maximum_assets}")
        return self


class EditorialShot(BaseModel):
    shot_id: str
    chapter_id: str = ""
    narration_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    start: float
    end: float
    duration: float = Field(gt=0)
    narration_text: str = ""
    visual_purpose: str = ""
    story_function: str = "support"
    visual_mode: Literal[
        "master_video",
        "master_video_with_overlay",
        "master_video_freeze",
        "coded_graphic",
        "archive_media",
        "generated_still",
        "black_or_negative_space",
    ] = "master_video"
    master_asset_id: str | None = None
    reuse_operation: Literal[
        "full_frame",
        "crop",
        "loop",
        "loop_and_slow",
        "slow",
        "freeze",
        "reverse_loop",
        "overlay_background",
        "callback",
        "match_cut",
    ] = "full_frame"
    crop_id: str | None = None
    playback_speed: float = Field(default=1.0, gt=0, le=4)
    source_in: float = Field(default=0, ge=0)
    source_out: float | None = Field(default=None, gt=0)
    overlay: OverlaySpec | None = None
    archive_source: str | None = None
    support_reason: str = ""
    transition: str = "hard_cut"

    @model_validator(mode="after")
    def validate_timing(self) -> "EditorialShot":
        if self.end <= self.start:
            raise ValueError("editorial shot end must be after start")
        expected = self.end - self.start
        if abs(self.duration - expected) > 0.01:
            self.duration = expected
        return self


class EditorialShotPlan(BaseModel):
    project_id: str
    shots: list[EditorialShot]
    total_seconds: float
    voiceover_sha256: str
    master_plan_version: int
    overlay_tracks: list[OverlaySpec] = Field(default_factory=list)


class V1MediaJob(BaseModel):
    job_id: str
    shot_id: str = ""  # Compatibility alias; new jobs set this to asset_id.
    asset_id: str = ""
    category: str = ""
    linked_shots: list[str] = Field(default_factory=list)
    media_type: Literal["image", "video"]
    status: Literal["pending", "generating", "review", "approved", "rejected", "failed", "manual_required"] = "pending"
    prompt: str
    output: str | None = None
    reference: str | None = None
    duration_seconds: float = 0
    resolution: str = "720p"
    aspect_ratio: str = "16:9"
    error: str | None = None
    updated_at: str = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def normalize_asset_id(self) -> "V1MediaJob":
        if not self.asset_id:
            self.asset_id = self.shot_id
        if not self.shot_id:
            self.shot_id = self.asset_id
        return self


class V1MediaManifest(BaseModel):
    project_id: str
    media_type: Literal["image", "video"]
    jobs: list[V1MediaJob]
    updated_at: str = Field(default_factory=utc_now)


class AnimaticManifest(BaseModel):
    project_id: str
    output: str
    duration_seconds: float
    voiceover_sha256: str
    sound_plan: str
    shots: list[str]
    created_at: str = Field(default_factory=utc_now)


class VideoJob(BaseModel):
    video_job_id: str
    asset_id: str
    category: str = ""
    input_image: str
    duration_seconds: float = 5
    prompt: str
    expected_filename: str
    linked_shots: list[str]


class VideoJobManifest(BaseModel):
    project_id: str
    jobs: list[VideoJob]


class NarrationTimestamp(BaseModel):
    narration_id: str
    start: float
    end: float


class TimelineEntry(BaseModel):
    timeline_id: str
    shot_id: str
    timeline_start: float | None = None
    timeline_end: float | None = None
    start: float | None = None
    end: float | None = None
    narration_ids: list[str]
    master_asset: str = ""
    source_media: str = ""
    media_kind: Literal["video", "image", "coded_graphic", "archive", "placeholder"]
    visual_mode: str = "master_video"
    playback_mode: str = "full_frame"
    playback_speed: float = Field(default=1.0, gt=0, le=4)
    source_in: float = Field(default=0, ge=0)
    source_out: float | None = None
    crop_id: str | None = None
    overlay_track_ids: list[str] = Field(default_factory=list)
    variant: str = "master"
    trim_in: float = 0
    trim_out: float | None = None
    transition_in: str = "hard_cut"
    transition_out: str = "hard_cut"

    @model_validator(mode="after")
    def normalize_timeline_fields(self) -> "TimelineEntry":
        if self.timeline_start is None:
            self.timeline_start = self.start if self.start is not None else 0.0
        if self.timeline_end is None:
            self.timeline_end = self.end if self.end is not None else self.timeline_start
        self.start = self.timeline_start
        self.end = self.timeline_end
        if self.timeline_end <= self.timeline_start:
            raise ValueError("timeline_end must be after timeline_start")
        return self


class Timeline(BaseModel):
    project_id: str
    entries: list[TimelineEntry]
    total_seconds: float
    overlay_tracks: dict[str, OverlaySpec] = Field(default_factory=dict)
