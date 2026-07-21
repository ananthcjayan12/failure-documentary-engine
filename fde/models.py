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
    SCRIPT_REVIEW = "SCRIPT_REVIEW"
    SCRIPT_APPROVED = "SCRIPT_APPROVED"
    SHOT_PLAN_READY = "SHOT_PLAN_READY"
    ASSET_PLAN_READY = "ASSET_PLAN_READY"
    IMAGE_GENERATION = "IMAGE_GENERATION"
    IMAGE_REVIEW = "IMAGE_REVIEW"
    IMAGES_APPROVED = "IMAGES_APPROVED"
    VIDEO_GENERATION = "VIDEO_GENERATION"
    VIDEO_REVIEW = "VIDEO_REVIEW"
    VIDEOS_APPROVED = "VIDEOS_APPROVED"
    NARRATION_READY = "NARRATION_READY"
    PREVIEW_REVIEW = "PREVIEW_REVIEW"
    PICTURE_LOCKED = "PICTURE_LOCKED"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    CHANGE_REQUESTED = "change_requested"
    REJECTED = "rejected"


class ProjectBrief(BaseModel):
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    title: str
    topic: str
    target_duration_seconds: float = Field(default=480, gt=30)
    tone: list[str] = Field(default_factory=lambda: ["investigative", "suspenseful", "respectful"])
    maximum_master_assets: int = Field(default=28, ge=1, le=60)
    master_video_duration_seconds: float = Field(default=5, ge=1, le=15)
    language: str = "English"
    audience: str = "General international audience"
    created_at: str = Field(default_factory=utc_now)


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
    estimated_start: float
    estimated_duration: float = Field(gt=0)
    mood: str = "investigative"
    intensity: float = Field(default=0.5, ge=0, le=1)
    claim_ids: list[str] = Field(default_factory=list)
    pause_after_seconds: float = Field(default=0, ge=0)


class DocumentaryScript(BaseModel):
    project_id: str
    title: str
    segments: list[NarrationSegment]
    estimated_total_seconds: float
    estimated_word_count: int


class Shot(BaseModel):
    shot_id: str
    chapter_id: str
    narration_ids: list[str]
    start: float
    duration: float = Field(gt=0)
    visual_purpose: str
    visual_type: str
    suggested_visual: str
    camera: str = ""
    motion: str = ""
    overlay_requirements: list[str] = Field(default_factory=list)
    suspense_function: str = "support"
    requires_new_master_asset: bool = True
    candidate_master_asset: str | None = None


class ShotPlan(BaseModel):
    project_id: str
    shots: list[Shot]
    total_seconds: float


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
    required_reuse_count: int = Field(ge=1)
    image_prompt: str = ""
    video_prompt: str = ""
    image_version: int = 0
    video_version: int = 0
    approved_image: str | None = None
    approved_video: str | None = None
    image_review: AssetReview = Field(default_factory=AssetReview)
    video_review: AssetReview = Field(default_factory=AssetReview)


class MasterAssetPlan(BaseModel):
    project_id: str
    maximum_assets: int
    assets: list[MasterAsset]
    uncovered_shots: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_limit(self) -> "MasterAssetPlan":
        if len(self.assets) > self.maximum_assets:
            raise ValueError(f"asset count {len(self.assets)} exceeds maximum {self.maximum_assets}")
        return self


class VideoJob(BaseModel):
    video_job_id: str
    asset_id: str
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
    start: float
    end: float
    narration_ids: list[str]
    master_asset: str
    source_media: str
    media_kind: Literal["video", "image", "placeholder"]
    variant: str = "master"
    trim_in: float = 0
    trim_out: float | None = None
    transition_in: str = "hard_cut"
    transition_out: str = "hard_cut"


class Timeline(BaseModel):
    project_id: str
    entries: list[TimelineEntry]
    total_seconds: float
