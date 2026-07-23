from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Literal

from pydantic import BaseModel, Field, model_validator

from .agents import get_agent
from .editorial import EditorialPlanValidationError, validate_editorial_plan
from .io import load_model, versioned_path, write_json
from .master_footage import (
    CATEGORY_PREFIX,
    MasterPlanValidationError,
    _category_defaults,
    approved_master_plan,
    validate_master_plan,
)
from .models import (
    AudioTiming,
    CropRegion,
    DisclosureLabel,
    DocumentaryScript,
    DocumentaryStructure,
    EditorialShot,
    EditorialShotPlan,
    MasterAsset,
    MasterAssetPlan,
    MasterFootageStrategy,
    OverlaySpec,
    ProjectState,
    ResearchDossier,
    Shot,
    ShotPlan,
    ShotSkeleton,
    ShotSkeletonPlan,
)
from .narration import clean_spoken_text
from .project import ProjectStore
from .prompts import render_prompt
from .timing import timing_is_current

WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)?")
SENTENCE_RE = re.compile(r"[^.!?]+(?:[.!?]+|$)")
CATEGORY_ORDER = ("hero", "atmosphere", "investigation")
ASSIGNMENT_BATCH_SIZE = 16


class CompactShot(BaseModel):
    shot_id: str
    chapter_id: str = ""
    start: float
    end: float
    duration: float = Field(gt=0)
    narration_summary: str
    claim_ids: list[str] = Field(default_factory=list)
    visual_need: str
    story_function: str
    importance: Literal["high", "medium", "low"] = "medium"


class CompactShotIndex(BaseModel):
    project_id: str
    voiceover_sha256: str
    total_seconds: float
    shots: list[CompactShot]


class VocabularyPackageOutline(BaseModel):
    asset_id: str
    category: Literal["hero", "atmosphere", "investigation"]
    title: str
    primary_story_role: str
    supported_shot_ids: list[str]
    supported_claim_ids: list[str] = Field(default_factory=list)
    supported_visual_needs: list[str] = Field(default_factory=list)
    continuity_family: str
    allowed_operations: list[str] = Field(default_factory=list)


class MasterVocabularyOutline(BaseModel):
    project_id: str
    packages: list[VocabularyPackageOutline]


class MasterPackageDetail(BaseModel):
    asset_id: str
    visual_concept: str
    factual_scope: list[str] = Field(default_factory=list)
    composition_requirements: list[str] = Field(default_factory=list)
    continuity_requirements: list[str] = Field(default_factory=list)
    subject_identity_requirements: list[str] = Field(default_factory=list)
    subject_geometry_requirements: list[str] = Field(default_factory=list)
    prohibited_details: list[str] = Field(default_factory=list)
    crop_regions: list[CropRegion] = Field(default_factory=list)
    overlay_safe_zones: list[str] = Field(default_factory=list)
    supported_overlay_families: list[str] = Field(default_factory=list)
    loopable: bool = False
    camera_stationary: bool = False
    seamless_loop_required: bool = False
    opening_frame_stable: bool = True
    ending_frame_stable: bool = True
    playback_speed_min: float = Field(default=0.5, gt=0, le=4)
    playback_speed_max: float = Field(default=1.25, gt=0, le=4)
    reconstruction_disclosure_required: bool = False

    @model_validator(mode="after")
    def validate_speed(self) -> "MasterPackageDetail":
        if self.playback_speed_max < self.playback_speed_min:
            raise ValueError("playback_speed_max must be >= playback_speed_min")
        return self


class MasterPackageDetailBatch(BaseModel):
    category: Literal["hero", "atmosphere", "investigation"]
    packages: list[MasterPackageDetail]


class AssignmentCandidate(BaseModel):
    asset_id: str
    score: float = Field(ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)


class ShotCandidateSet(BaseModel):
    shot_id: str
    candidates: list[AssignmentCandidate]
    local_confidence: float = Field(ge=0, le=1)
    margin: float = Field(ge=0, le=1)
    assigned_locally: bool = False


class AssignmentDecision(BaseModel):
    shot_id: str
    asset_id: str
    reuse_operation: Literal[
        "full_frame",
        "crop",
        "loop",
        "loop_and_slow",
        "slow",
        "freeze",
        "overlay_background",
        "callback",
        "match_cut",
    ] = "full_frame"
    crop_id: str | None = None
    playback_speed: float = Field(default=1.0, gt=0, le=4)
    source_in: float = Field(default=0, ge=0)
    source_out: float | None = Field(default=None, gt=0)
    visual_mode: Literal[
        "master_video",
        "master_video_with_overlay",
        "master_video_freeze",
        "generated_still",
    ] = "master_video"
    overlay_type: str | None = None
    overlay_template_id: str | None = None
    support_reason: str
    confidence: float = Field(default=0.8, ge=0, le=1)


class AssignmentBatch(BaseModel):
    assignments: list[AssignmentDecision]


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _load_script(project_dir: Path) -> DocumentaryScript:
    path = project_dir / "03_narration/narration.json"
    if not path.exists():
        path = project_dir / "03_script/script.json"
    return load_model(path, DocumentaryScript)


def _sentence_boundaries(
    timing: AudioTiming,
    script: DocumentaryScript,
) -> dict[float, tuple[float, str]]:
    """Return candidate timestamp -> (semantic strength, reason)."""
    words_by_paragraph: dict[str, list] = defaultdict(list)
    for word in timing.words:
        words_by_paragraph[word.paragraph_id].append(word)
    candidates: dict[float, tuple[float, str]] = {}

    for segment in script.segments:
        timed_words = words_by_paragraph.get(segment.narration_id, [])
        if not timed_words:
            continue
        text = clean_spoken_text(segment.text)
        cumulative = 0
        sentences = [
            item.group(0).strip()
            for item in SENTENCE_RE.finditer(text)
            if item.group(0).strip()
        ]
        for sentence_index, sentence in enumerate(sentences):
            cumulative += len(WORD_RE.findall(sentence))
            if sentence_index + 1 >= len(sentences):
                continue
            if 0 < cumulative < len(timed_words):
                timestamp = round(timed_words[cumulative].start, 3)
                candidates[timestamp] = max(
                    candidates.get(timestamp, (0.0, "")),
                    (1.0, "sentence_end"),
                    key=lambda item: item[0],
                )
        paragraph_end = round(timed_words[-1].end, 3)
        candidates[paragraph_end] = max(
            candidates.get(paragraph_end, (0.0, "")),
            (1.35, "paragraph_end"),
            key=lambda item: item[0],
        )

    for previous, following in zip(timing.words, timing.words[1:]):
        gap = max(0.0, following.start - previous.end)
        if gap >= 0.18:
            timestamp = round(following.start, 3)
            strength = min(1.1, 0.35 + gap)
            candidates[timestamp] = max(
                candidates.get(timestamp, (0.0, "")),
                (strength, "measured_pause"),
                key=lambda item: item[0],
            )
    return candidates


def semantic_boundaries(
    timing: AudioTiming,
    script: DocumentaryScript,
    *,
    minimum: float = 2.5,
    preferred_minimum: float = 4.0,
    target: float = 6.5,
    soft_maximum: float = 10.0,
    hard_maximum: float = 12.0,
) -> list[float]:
    """Create edit beats from narration semantics rather than source-video duration."""
    end = timing.audio_duration_seconds
    candidates = _sentence_boundaries(timing, script)
    all_word_starts = sorted({round(item.start, 3) for item in timing.words})
    result = [0.0]
    cursor = 0.0

    while end - cursor > hard_maximum:
        eligible: list[tuple[float, float, str]] = []
        for timestamp, (strength, reason) in candidates.items():
            duration = timestamp - cursor
            if minimum <= duration <= hard_maximum:
                score = (
                    strength * 4.0
                    - abs(duration - target) * 0.30
                    - max(0.0, preferred_minimum - duration) * 0.45
                    - max(0.0, duration - soft_maximum) * 0.55
                )
                eligible.append((timestamp, score, reason))
        if eligible:
            chosen = max(eligible, key=lambda item: (item[1], -item[0]))[0]
        else:
            fallback = [
                point
                for point in all_word_starts
                if cursor + minimum <= point <= cursor + hard_maximum
            ]
            chosen = fallback[-1] if fallback else min(end, cursor + hard_maximum)
        if chosen <= cursor + 0.001:
            break
        result.append(round(chosen, 3))
        cursor = chosen

    if end - result[-1] < minimum and len(result) > 1:
        result.pop()
    result.append(round(end, 3))
    return result


def _shot_text(timing: AudioTiming, start: float, end: float) -> tuple[str, list[str]]:
    selected = [item for item in timing.words if item.start < end and item.end > start]
    paragraph_ids = list(dict.fromkeys(item.paragraph_id for item in selected))
    return " ".join(item.word for item in selected), paragraph_ids


def _story_function(index: int, total: int, chapter_id: str, text: str) -> str:
    lowered = f"{chapter_id} {text}".lower()
    if index == 1:
        return "cold_open"
    if index == total:
        return "human_resolution"
    if any(
        value in lowered
        for value in ("evidence", "radar", "satellite", "search", "investigation")
    ):
        return "evidence_explanation"
    if any(
        value in lowered
        for value in ("warning", "critical", "failure", "impact", "collapse")
    ):
        return "physical_story_moment"
    if "?" in text:
        return "question_or_mystery"
    return "narrative_progression"


def _visual_need(story_function: str) -> str:
    return {
        "cold_open": "establishing_mystery",
        "physical_story_moment": "physical_event",
        "evidence_explanation": "technical_explanation",
        "question_or_mystery": "investigative_tension",
        "human_resolution": "human_context",
    }.get(story_function, "narrative_support")


def _importance(story_function: str) -> Literal["high", "medium", "low"]:
    if story_function in {
        "cold_open",
        "physical_story_moment",
        "evidence_explanation",
        "human_resolution",
    }:
        return "high"
    if story_function == "question_or_mystery":
        return "medium"
    return "low"


def _summary(text: str, maximum_words: int = 28) -> str:
    words = text.split()
    if len(words) <= maximum_words:
        return text.strip()
    return " ".join(words[:maximum_words]).rstrip(",;:") + "…"


def plan_semantic_shot_skeleton(
    project_dir: Path,
    *,
    minimum: float = 2.5,
    target: float = 6.5,
    maximum: float = 12.0,
) -> ShotSkeletonPlan:
    project_dir = Path(project_dir)
    if not timing_is_current(project_dir):
        raise RuntimeError("current voice timing is required before shot-skeleton planning")
    timing = load_model(project_dir / "05_timing/audio_timing.json", AudioTiming)
    script = _load_script(project_dir)
    segment_by_id = {item.narration_id: item for item in script.segments}
    points = semantic_boundaries(
        timing,
        script,
        minimum=minimum,
        target=target,
        hard_maximum=maximum,
    )
    skeletons: list[ShotSkeleton] = []
    total = len(points) - 1
    for index, (start, end) in enumerate(zip(points, points[1:]), start=1):
        narration_text, paragraph_ids = _shot_text(timing, start, end)
        segments = [segment_by_id[item] for item in paragraph_ids if item in segment_by_id]
        chapter_id = segments[0].chapter_id if segments else ""
        claim_ids = _dedupe(
            claim for segment in segments for claim in segment.claim_ids
        )
        story_function = _story_function(index, total, chapter_id, narration_text)
        skeletons.append(
            ShotSkeleton(
                shot_id=f"SHOT_{index:03d}",
                chapter_id=chapter_id,
                narration_ids=paragraph_ids,
                claim_ids=claim_ids,
                start=start,
                end=end,
                duration=end - start,
                narration_text=narration_text,
                visual_purpose=_visual_need(story_function),
                story_function=story_function,
                factual_scope=claim_ids,
            )
        )
    plan = ShotSkeletonPlan(
        project_id=script.project_id,
        shots=skeletons,
        total_seconds=timing.audio_duration_seconds,
        voiceover_sha256=timing.voiceover_sha256,
        timing_source=f"{timing.source}+semantic_sentence_pause_segmentation",
    )
    root = project_dir / "06_shots"
    write_json(root / "shot_skeleton.json", plan)
    write_json(root / "compact_shot_index.json", build_compact_shot_index(plan))

    legacy = ShotPlan(
        project_id=plan.project_id,
        total_seconds=plan.total_seconds,
        voiceover_sha256=plan.voiceover_sha256,
        shots=[
            Shot(
                shot_id=item.shot_id,
                chapter_id=item.chapter_id,
                narration_ids=item.narration_ids,
                claim_ids=item.claim_ids,
                start=item.start,
                end=item.end,
                duration=item.duration,
                narration_text=item.narration_text,
                visual_purpose=item.visual_purpose,
                story_function=item.story_function,
                factual_scope=item.factual_scope,
                visual_type="unassigned",
                requires_new_master_asset=False,
            )
            for item in plan.shots
        ],
    )
    write_json(root / "shot_plan.json", legacy)
    write_json(project_dir / "04_shot_plan/shot_plan.json", legacy)
    return plan


def build_compact_shot_index(skeleton: ShotSkeletonPlan) -> CompactShotIndex:
    return CompactShotIndex(
        project_id=skeleton.project_id,
        voiceover_sha256=skeleton.voiceover_sha256,
        total_seconds=skeleton.total_seconds,
        shots=[
            CompactShot(
                shot_id=item.shot_id,
                chapter_id=item.chapter_id,
                start=item.start,
                end=item.end,
                duration=item.duration,
                narration_summary=_summary(item.narration_text),
                claim_ids=item.claim_ids,
                visual_need=_visual_need(item.story_function),
                story_function=item.story_function,
                importance=_importance(item.story_function),
            )
            for item in skeleton.shots
        ],
    )


def _expected_ids(strategy: MasterFootageStrategy) -> list[str]:
    return [
        *[f"H{index:02d}" for index in range(1, strategy.hero_count + 1)],
        *[f"L{index:02d}" for index in range(1, strategy.atmosphere_count + 1)],
        *[f"E{index:02d}" for index in range(1, strategy.investigation_count + 1)],
    ]


def _desired_category(shot: CompactShot) -> str:
    if shot.story_function in {"cold_open", "physical_story_moment", "human_resolution"}:
        return "hero"
    if shot.story_function == "evidence_explanation":
        return "investigation"
    return "atmosphere"


def _default_operations(category: str) -> list[str]:
    if category == "hero":
        return ["full_frame", "crop", "slow", "freeze", "callback", "match_cut"]
    if category == "atmosphere":
        return [
            "full_frame",
            "crop",
            "loop",
            "slow",
            "freeze",
            "overlay_background",
            "callback",
        ]
    return [
        "full_frame",
        "crop",
        "slow",
        "freeze",
        "overlay_background",
        "callback",
    ]


def deterministic_outline(
    compact: CompactShotIndex,
    strategy: MasterFootageStrategy,
) -> MasterVocabularyOutline:
    by_category: dict[str, list[CompactShot]] = defaultdict(list)
    for shot in compact.shots:
        by_category[_desired_category(shot)].append(shot)
    packages: list[VocabularyPackageOutline] = []
    pools: dict[str, list[VocabularyPackageOutline]] = defaultdict(list)
    counts = {
        "hero": strategy.hero_count,
        "atmosphere": strategy.atmosphere_count,
        "investigation": strategy.investigation_count,
    }
    all_shots = compact.shots
    if not all_shots:
        raise ValueError("compact shot index is empty")
    for category in CATEGORY_ORDER:
        category_shots = by_category.get(category) or all_shots
        for index in range(1, counts[category] + 1):
            seed = category_shots[(index - 1) % len(category_shots)]
            asset_id = f"{CATEGORY_PREFIX[category]}{index:02d}"
            package = VocabularyPackageOutline(
                asset_id=asset_id,
                category=category,
                title=f"{category.title()} vocabulary — {_summary(seed.narration_summary, 8)}",
                primary_story_role=seed.visual_need,
                supported_shot_ids=[seed.shot_id],
                supported_claim_ids=list(seed.claim_ids),
                supported_visual_needs=[seed.visual_need],
                continuity_family=f"{category}_{seed.chapter_id or index}",
                allowed_operations=_default_operations(category),
            )
            packages.append(package)
            pools[category].append(package)
    usage: dict[str, int] = defaultdict(int)
    for shot in compact.shots:
        category = _desired_category(shot)
        pool = pools.get(category) or packages
        package = min(pool, key=lambda item: (usage[item.asset_id], item.asset_id))
        usage[package.asset_id] += 1
        if shot.shot_id not in package.supported_shot_ids:
            package.supported_shot_ids.append(shot.shot_id)
        package.supported_claim_ids = _dedupe(
            [*package.supported_claim_ids, *shot.claim_ids]
        )
        package.supported_visual_needs = _dedupe(
            [*package.supported_visual_needs, shot.visual_need]
        )
    return MasterVocabularyOutline(project_id=compact.project_id, packages=packages)


def validate_outline(
    outline: MasterVocabularyOutline,
    compact: CompactShotIndex,
    strategy: MasterFootageStrategy,
) -> None:
    errors: list[str] = []
    if outline.project_id != compact.project_id:
        errors.append("Vocabulary outline changed project_id.")
    expected_ids = _expected_ids(strategy)
    actual_ids = [item.asset_id for item in outline.packages]
    if actual_ids != expected_ids:
        errors.append(
            "Vocabulary package IDs must be exactly ordered as configured "
            "(H packages, then L packages, then E packages)."
        )
    counts = Counter(item.category for item in outline.packages)
    expected_counts = {
        "hero": strategy.hero_count,
        "atmosphere": strategy.atmosphere_count,
        "investigation": strategy.investigation_count,
    }
    for category, count in expected_counts.items():
        if counts.get(category, 0) != count:
            errors.append(f"Expected {count} {category} package outlines.")
    known_shots = {item.shot_id for item in compact.shots}
    known_claims = {claim for item in compact.shots for claim in item.claim_ids}
    covered: set[str] = set()
    for package in outline.packages:
        if not package.supported_shot_ids:
            errors.append(f"{package.asset_id} has no supported shots.")
        unknown = [item for item in package.supported_shot_ids if item not in known_shots]
        if unknown:
            errors.append(
                f"{package.asset_id} references unknown shots: {', '.join(unknown)}."
            )
        covered.update(item for item in package.supported_shot_ids if item in known_shots)
        unknown_claims = [
            item for item in package.supported_claim_ids if item not in known_claims
        ]
        if unknown_claims:
            errors.append(
                f"{package.asset_id} references unsupported claims: "
                + ", ".join(unknown_claims)
            )
        if not package.primary_story_role.strip() or not package.continuity_family.strip():
            errors.append(f"{package.asset_id} needs a story role and continuity family.")
        if not package.allowed_operations:
            errors.append(f"{package.asset_id} needs allowed reuse operations.")
    missing = sorted(known_shots - covered)
    if missing:
        errors.append("Vocabulary outline leaves shots uncovered: " + ", ".join(missing))
    if errors:
        raise MasterPlanValidationError("\n".join(errors))


def deterministic_details(
    category: Literal["hero", "atmosphere", "investigation"],
    outlines: list[VocabularyPackageOutline],
) -> MasterPackageDetailBatch:
    packages: list[MasterPackageDetail] = []
    for outline in outlines:
        if category == "hero":
            crop_regions = [
                CropRegion(crop_id="wide_event", description="Full physical story moment"),
                CropRegion(
                    crop_id="subject_detail",
                    description="Stable identity-preserving detail",
                ),
            ]
        elif category == "atmosphere":
            crop_regions = [
                CropRegion(
                    crop_id="wide_environment",
                    description="Overlay-safe environmental wide",
                ),
                CropRegion(
                    crop_id="texture_detail",
                    description="Secondary loop-safe texture detail",
                ),
            ]
        else:
            crop_regions = [
                CropRegion(
                    crop_id="wide_investigation",
                    description="Full investigation environment",
                ),
                CropRegion(
                    crop_id="evidence_detail",
                    description="Replaceable evidence or monitor detail",
                ),
            ]
        packages.append(
            MasterPackageDetail(
                asset_id=outline.asset_id,
                visual_concept=(
                    f"A factual, technically credible {category} visual vocabulary package "
                    f"for {outline.primary_story_role}."
                ),
                factual_scope=list(outline.supported_claim_ids),
                composition_requirements=[
                    "cinematic 16:9 frame",
                    "stable wide composition",
                    "clean secondary crop region",
                ],
                continuity_requirements=[
                    f"remain inside continuity family {outline.continuity_family}",
                    "preserve identity, geometry, lighting, time and weather",
                ],
                subject_identity_requirements=[
                    "do not change established subject identity"
                ],
                subject_geometry_requirements=[
                    "preserve physically credible scale and geometry"
                ],
                prohibited_details=[
                    "unsupported damage",
                    "unsupported weather",
                    "embedded text",
                    "watermark",
                    "invented evidence",
                ],
                crop_regions=crop_regions,
                overlay_safe_zones=["upper_right", "center"],
                supported_overlay_families=(
                    [
                        "map",
                        "radar",
                        "timeline",
                        "transcript",
                        "satellite_arc",
                        "technical_diagram",
                    ]
                    if category == "investigation"
                    else []
                ),
                loopable=category == "atmosphere",
                camera_stationary=category == "atmosphere",
                seamless_loop_required=category == "atmosphere",
                playback_speed_min=0.5,
                playback_speed_max=1.25,
                reconstruction_disclosure_required=category == "investigation",
            )
        )
    return MasterPackageDetailBatch(category=category, packages=packages)


def validate_detail_batch(
    batch: MasterPackageDetailBatch,
    outlines: list[VocabularyPackageOutline],
) -> None:
    errors: list[str] = []
    expected_ids = [item.asset_id for item in outlines]
    actual_ids = [item.asset_id for item in batch.packages]
    if outlines and batch.category != outlines[0].category:
        errors.append("Detail batch category does not match its outline category.")
    if actual_ids != expected_ids:
        errors.append("Detail batch must return exactly the requested package IDs in order.")
    outline_by_id = {item.asset_id: item for item in outlines}
    for detail in batch.packages:
        outline = outline_by_id.get(detail.asset_id)
        if outline is None:
            continue
        unsupported = [
            claim
            for claim in detail.factual_scope
            if claim not in outline.supported_claim_ids
        ]
        if unsupported:
            errors.append(
                f"{detail.asset_id} expanded factual scope beyond the approved outline: "
                + ", ".join(unsupported)
            )
        if len(detail.crop_regions) < 2:
            errors.append(f"{detail.asset_id} needs at least two useful crop regions.")
        if not detail.visual_concept.strip():
            errors.append(f"{detail.asset_id} has no visual concept.")
        if batch.category == "atmosphere":
            if (
                not detail.loopable
                or not detail.camera_stationary
                or not detail.seamless_loop_required
            ):
                errors.append(
                    f"{detail.asset_id} must be stationary and seamlessly loopable."
                )
        if (
            batch.category == "investigation"
            and not detail.reconstruction_disclosure_required
        ):
            errors.append(
                f"{detail.asset_id} must require a reconstruction disclosure."
            )
    if errors:
        raise MasterPlanValidationError("\n".join(errors))


def _chapter_summaries(
    project: Path,
    script: DocumentaryScript,
) -> list[dict[str, Any]]:
    path = project / "02_structure/structure.json"
    if path.exists():
        structure = load_model(path, DocumentaryStructure)
        return [
            {
                "chapter_id": item.chapter_id,
                "title": item.title,
                "narrative_purpose": item.narrative_purpose,
                "reveal": item.reveal,
            }
            for item in structure.chapters
        ]
    grouped: dict[str, list[str]] = defaultdict(list)
    for segment in script.segments:
        grouped[segment.chapter_id].append(clean_spoken_text(segment.text))
    return [
        {
            "chapter_id": chapter_id,
            "title": chapter_id,
            "narrative_purpose": _summary(" ".join(texts), 36),
            "reveal": "",
        }
        for chapter_id, texts in grouped.items()
    ]


def _claim_ledger(research: ResearchDossier) -> list[dict[str, Any]]:
    return [
        {
            "claim_id": item.claim_id,
            "statement": item.statement,
            "status": item.status,
            "allowed_language": item.allowed_language,
            "prohibited_language": item.prohibited_language,
        }
        for item in research.claims
    ]


def _combine_plan(
    outline: MasterVocabularyOutline,
    details: list[MasterPackageDetailBatch],
    *,
    brief,
    skeleton: ShotSkeletonPlan,
    version: int,
) -> MasterAssetPlan:
    detail_by_id = {
        package.asset_id: package
        for batch in details
        for package in batch.packages
    }
    assets: list[MasterAsset] = []
    for package in outline.packages:
        detail = detail_by_id[package.asset_id]
        asset = MasterAsset(
            asset_id=package.asset_id,
            title=package.title,
            category=package.category,
            linked_shots=list(package.supported_shot_ids),
            primary_use=package.primary_story_role,
            secondary_uses=list(package.supported_visual_needs),
            required_reuse_count=max(1, len(package.supported_shot_ids)),
            factual_scope=list(detail.factual_scope or package.supported_claim_ids),
            factual_context_id=package.continuity_family,
            source_duration_seconds=(
                brief.master_footage_strategy.source_video_duration_seconds
            ),
            loopable=detail.loopable,
            allowed_operations=list(package.allowed_operations),
            crop_regions=list(detail.crop_regions),
            overlay_safe_zones=list(detail.overlay_safe_zones),
            continuity_requirements=list(detail.continuity_requirements),
            prohibited_details=list(detail.prohibited_details),
            camera_stationary=detail.camera_stationary,
            seamless_loop_required=detail.seamless_loop_required,
            subject_identity_requirements=list(detail.subject_identity_requirements),
            subject_geometry_requirements=list(detail.subject_geometry_requirements),
            reconstruction_disclosure=(
                DisclosureLabel(required=True)
                if detail.reconstruction_disclosure_required
                else None
            ),
            playback_speed_min=detail.playback_speed_min,
            playback_speed_max=detail.playback_speed_max,
            supported_overlay_families=list(detail.supported_overlay_families),
            opening_frame_stable=detail.opening_frame_stable,
            ending_frame_stable=detail.ending_frame_stable,
            major_story_moment=package.category == "hero",
            reuse_rationale=(
                f"{package.asset_id} is a reusable member of "
                f"{package.continuity_family}; it supports "
                f"{len(package.supported_shot_ids)} compact audio-led beats without "
                "changing their immutable timing."
            ),
        )
        assets.append(_category_defaults(asset, brief.master_footage_strategy))
    return MasterAssetPlan(
        project_id=skeleton.project_id,
        maximum_assets=brief.maximum_master_assets,
        strategy=brief.master_footage_strategy.model_copy(deep=True),
        plan_version=version,
        status="proposal",
        assets=assets,
        uncovered_shots=[],
    )


def plan_master_footage_compact(
    store: ProjectStore,
    project_id: str,
    *,
    agent_kind: str = "routed",
    consume_response: bool = False,
) -> MasterAssetPlan:
    project = store.project_dir(project_id)
    brief = store.brief(project_id)
    skeleton = load_model(project / "06_shots/shot_skeleton.json", ShotSkeletonPlan)
    timing = load_model(project / "05_timing/audio_timing.json", AudioTiming)
    if skeleton.voiceover_sha256 != timing.voiceover_sha256:
        raise RuntimeError("shot skeleton does not match the current approved voiceover")
    compact = build_compact_shot_index(skeleton)
    write_json(project / "06_shots/compact_shot_index.json", compact)
    version = store.next_version(project_id, "master_footage")
    store.transition(project_id, ProjectState.MASTER_PLAN_GENERATING)

    research = load_model(project / "01_research/source_dossier.json", ResearchDossier)
    script = _load_script(project)
    chapters = _chapter_summaries(project, script)
    claims = _claim_ledger(research)
    context = {
        "project_id": project_id,
        "title": brief.title,
        "duration": brief.target_duration_seconds,
    }

    try:
        if agent_kind in {"deterministic", "mock"}:
            outline = deterministic_outline(compact, brief.master_footage_strategy)
        else:
            agent = get_agent(agent_kind, context, consume_response)
            outline = agent.run(
                stage="master_vocabulary_outline",
                prompt=render_prompt(
                    "master_vocabulary_outline",
                    brief=brief,
                    chapter_summaries=chapters,
                    claim_ledger=claims,
                    compact_shot_index=compact,
                    strategy=brief.master_footage_strategy,
                ),
                output_model=MasterVocabularyOutline,
                request_dir=project / "_requests",
            )
        validate_outline(outline, compact, brief.master_footage_strategy)
        write_json(project / "05_master_assets/master_vocabulary_outline.json", outline)

        detail_batches: list[MasterPackageDetailBatch] = []
        for category in CATEGORY_ORDER:
            category_outlines = [
                item for item in outline.packages if item.category == category
            ]
            relevant_shot_ids = {
                shot_id
                for item in category_outlines
                for shot_id in item.supported_shot_ids
            }
            relevant_shots = [
                item for item in compact.shots if item.shot_id in relevant_shot_ids
            ]
            relevant_claim_ids = {
                claim
                for item in category_outlines
                for claim in item.supported_claim_ids
            }
            relevant_claims = [
                item for item in claims if item["claim_id"] in relevant_claim_ids
            ]
            if agent_kind in {"deterministic", "mock"}:
                batch = deterministic_details(category, category_outlines)
            else:
                agent = get_agent(agent_kind, context, consume_response)
                batch = agent.run(
                    stage=f"master_package_details_{category}",
                    prompt=render_prompt(
                        "master_package_details",
                        category=category,
                        approved_outline=outline,
                        requested_packages=category_outlines,
                        relevant_shots=relevant_shots,
                        relevant_claims=relevant_claims,
                        strategy=brief.master_footage_strategy,
                    ),
                    output_model=MasterPackageDetailBatch,
                    request_dir=project / "_requests",
                )
            validate_detail_batch(batch, category_outlines)
            detail_batches.append(batch)
            write_json(
                project
                / "05_master_assets"
                / f"master_package_details_{category}.json",
                batch,
            )

        proposal = _combine_plan(
            outline,
            detail_batches,
            brief=brief,
            skeleton=skeleton,
            version=version,
        )
        validate_master_plan(proposal, skeleton, brief)
    except Exception:
        store.transition(project_id, ProjectState.SHOT_SKELETON_APPROVED)
        raise

    root = project / "05_master_assets"
    write_json(versioned_path(root, "master_footage_plan", ".json", version), proposal)
    write_json(root / "master_footage_plan.json", proposal)
    write_json(
        root / "validation_report.json",
        {
            "valid": True,
            "version": version,
            "planning_calls": {
                "global_outline": 1,
                "category_detail_batches": 3,
                "full_shot_plan_returned_by_model": False,
            },
            "category_counts": dict(
                Counter(item.category for item in proposal.assets)
            ),
            "asset_count": len(proposal.assets),
            "compact_shot_count": len(compact.shots),
            "covered_shots": len(skeleton.shots),
            "uncovered_shots": [],
        },
    )
    store.transition(project_id, ProjectState.MASTER_PLAN_REVIEW)
    return proposal


def _tokens(value: str) -> set[str]:
    return {
        token.lower()
        for token in WORD_RE.findall(value)
        if len(token) > 2
    }


def _score_candidates(
    compact: CompactShotIndex,
    master_plan: MasterAssetPlan,
) -> tuple[list[ShotCandidateSet], dict[str, AssignmentDecision], list[str]]:
    asset_by_id = {item.asset_id: item for item in master_plan.assets}
    usage: dict[str, int] = defaultdict(int)
    local: dict[str, AssignmentDecision] = {}
    candidate_sets: list[ShotCandidateSet] = []
    ambiguous: list[str] = []
    previous_asset: str | None = None

    for shot in compact.shots:
        supported = [
            asset
            for asset in master_plan.assets
            if shot.shot_id in asset.linked_shots
        ]
        if not supported:
            raise EditorialPlanValidationError(
                f"{shot.shot_id} has no approved master-footage candidates."
            )
        desired = _desired_category(shot)
        shot_tokens = _tokens(
            f"{shot.narration_summary} {shot.visual_need} {shot.story_function}"
        )
        scored: list[AssignmentCandidate] = []
        for asset in supported:
            reasons = ["approved shot coverage"]
            score = 0.35
            if shot.claim_ids:
                overlap = len(
                    set(shot.claim_ids) & set(asset.factual_scope)
                ) / len(set(shot.claim_ids))
                score += 0.25 * overlap
                if overlap:
                    reasons.append("claim scope overlap")
            if asset.category == desired:
                score += 0.15
                reasons.append("visual-need category match")
            if shot.chapter_id and shot.chapter_id in asset.factual_context_id:
                score += 0.10
                reasons.append("chapter continuity")
            asset_tokens = _tokens(
                " ".join([asset.title, asset.primary_use, *asset.secondary_uses])
            )
            union = shot_tokens | asset_tokens
            if union:
                lexical = len(shot_tokens & asset_tokens) / len(union)
                score += 0.10 * min(1.0, lexical * 4.0)
                if lexical:
                    reasons.append("semantic role overlap")
            score += 0.05 / (1 + usage[asset.asset_id])
            if previous_asset == asset.asset_id and len(supported) > 1:
                score -= 0.12
                reasons.append("adjacent repetition penalty")
            scored.append(
                AssignmentCandidate(
                    asset_id=asset.asset_id,
                    score=round(max(0.0, min(1.0, score)), 4),
                    reasons=reasons,
                )
            )
        scored.sort(key=lambda item: (-item.score, item.asset_id))
        top = scored[0]
        second = scored[1].score if len(scored) > 1 else 0.0
        margin = max(0.0, top.score - second)
        confident = len(scored) == 1 or (top.score >= 0.78 and margin >= 0.12)
        candidate_sets.append(
            ShotCandidateSet(
                shot_id=shot.shot_id,
                candidates=scored[:3],
                local_confidence=top.score,
                margin=round(margin, 4),
                assigned_locally=confident,
            )
        )
        if confident:
            asset = asset_by_id[top.asset_id]
            decision = _default_decision(shot, asset, usage[asset.asset_id])
            local[shot.shot_id] = decision
            usage[asset.asset_id] += 1
            previous_asset = asset.asset_id
        else:
            ambiguous.append(shot.shot_id)
    return candidate_sets, local, ambiguous


def _default_decision(
    shot: CompactShot,
    asset: MasterAsset,
    prior_usage: int,
) -> AssignmentDecision:
    if shot.duration > asset.source_duration_seconds and asset.loopable:
        operation = "loop_and_slow" if asset.playback_speed_min <= 0.8 else "loop"
        speed = max(asset.playback_speed_min, 0.8)
    elif shot.duration > asset.source_duration_seconds:
        operation = "freeze"
        speed = 1.0
    elif prior_usage:
        operation = "callback"
        speed = 1.0
    else:
        operation = "full_frame"
        speed = 1.0
    if operation == "loop_and_slow" and "loop" not in asset.allowed_operations:
        operation = "freeze"
    if operation not in asset.allowed_operations and operation != "loop_and_slow":
        operation = asset.allowed_operations[0]
    crop_id = (
        asset.crop_regions[prior_usage % len(asset.crop_regions)].crop_id
        if asset.crop_regions
        else None
    )
    visual_mode = "master_video_freeze" if operation == "freeze" else "master_video"
    return AssignmentDecision(
        shot_id=shot.shot_id,
        asset_id=asset.asset_id,
        reuse_operation=operation,
        crop_id=crop_id,
        playback_speed=speed,
        source_in=0,
        source_out=asset.source_duration_seconds,
        visual_mode=visual_mode,
        support_reason=(
            f"Local candidate scoring selected {asset.asset_id} from the approved "
            f"vocabulary for {shot.visual_need}; timing remains owned by the audio skeleton."
        ),
        confidence=0.9,
    )


def _compact_asset_registry(plan: MasterAssetPlan) -> list[dict[str, Any]]:
    return [
        {
            "asset_id": item.asset_id,
            "category": item.category,
            "title": item.title,
            "primary_use": item.primary_use,
            "linked_shots": item.linked_shots,
            "factual_scope": item.factual_scope,
            "allowed_operations": item.allowed_operations,
            "crop_ids": [crop.crop_id for crop in item.crop_regions],
            "playback_speed_min": item.playback_speed_min,
            "playback_speed_max": item.playback_speed_max,
            "source_duration_seconds": item.source_duration_seconds,
            "supported_overlay_families": item.supported_overlay_families,
        }
        for item in plan.assets
    ]


def _validate_assignment_decision(
    decision: AssignmentDecision,
    *,
    shot: CompactShot,
    candidate_set: ShotCandidateSet,
    assets: dict[str, MasterAsset],
) -> None:
    allowed_candidate_ids = {item.asset_id for item in candidate_set.candidates}
    if decision.shot_id != shot.shot_id:
        raise EditorialPlanValidationError(
            f"Assignment batch returned {decision.shot_id} for requested {shot.shot_id}."
        )
    if decision.asset_id not in allowed_candidate_ids:
        raise EditorialPlanValidationError(
            f"{shot.shot_id} selected {decision.asset_id}, which was not one of its "
            "approved candidates."
        )
    asset = assets[decision.asset_id]
    operation = (
        "loop" if decision.reuse_operation == "loop_and_slow" else decision.reuse_operation
    )
    if operation not in asset.allowed_operations:
        raise EditorialPlanValidationError(
            f"{shot.shot_id} uses unsupported operation {decision.reuse_operation} "
            f"on {asset.asset_id}."
        )
    crop_ids = {item.crop_id for item in asset.crop_regions}
    if decision.crop_id and decision.crop_id not in crop_ids:
        raise EditorialPlanValidationError(
            f"{shot.shot_id} uses unknown crop {decision.crop_id} on {asset.asset_id}."
        )
    if not (
        asset.playback_speed_min
        <= decision.playback_speed
        <= asset.playback_speed_max
    ):
        raise EditorialPlanValidationError(
            f"{shot.shot_id} playback speed is outside {asset.asset_id}'s approved range."
        )
    source_out = decision.source_out or asset.source_duration_seconds
    if (
        decision.source_in >= source_out
        or source_out > asset.source_duration_seconds + 0.01
    ):
        raise EditorialPlanValidationError(
            f"{shot.shot_id} returned an invalid source range for {asset.asset_id}."
        )


def _model_assignment_batches(
    *,
    store: ProjectStore,
    project_id: str,
    compact: CompactShotIndex,
    master_plan: MasterAssetPlan,
    candidate_sets: list[ShotCandidateSet],
    local: dict[str, AssignmentDecision],
    ambiguous_ids: list[str],
    agent_kind: str,
    consume_response: bool,
) -> dict[str, AssignmentDecision]:
    if not ambiguous_ids:
        return {}
    project = store.project_dir(project_id)
    candidate_by_shot = {item.shot_id: item for item in candidate_sets}
    shot_by_id = {item.shot_id: item for item in compact.shots}
    assets = {item.asset_id: item for item in master_plan.assets}
    ordered_ids = [item.shot_id for item in compact.shots]
    result: dict[str, AssignmentDecision] = {}
    context = {
        "project_id": project_id,
        "title": store.brief(project_id).title,
        "duration": compact.total_seconds,
    }
    for batch_index, start in enumerate(
        range(0, len(ambiguous_ids), ASSIGNMENT_BATCH_SIZE),
        start=1,
    ):
        batch_ids = ambiguous_ids[start : start + ASSIGNMENT_BATCH_SIZE]
        relevant_asset_ids = {
            candidate.asset_id
            for shot_id in batch_ids
            for candidate in candidate_by_shot[shot_id].candidates
        }
        registry = [
            item
            for item in _compact_asset_registry(master_plan)
            if item["asset_id"] in relevant_asset_ids
        ]
        neighbours = []
        for shot_id in batch_ids:
            index = ordered_ids.index(shot_id)
            previous_id = ordered_ids[index - 1] if index else None
            next_id = (
                ordered_ids[index + 1]
                if index + 1 < len(ordered_ids)
                else None
            )
            previous_decision = (
                local.get(previous_id) if previous_id else None
            ) or (result.get(previous_id) if previous_id else None)
            neighbours.append(
                {
                    "shot_id": shot_id,
                    "previous_shot_id": previous_id,
                    "previous_asset_id": (
                        previous_decision.asset_id if previous_decision else None
                    ),
                    "next_shot_id": next_id,
                    "next_asset_id": (
                        local[next_id].asset_id
                        if next_id and next_id in local
                        else None
                    ),
                }
            )
        agent = get_agent(agent_kind, context, consume_response)
        response = agent.run(
            stage=f"editorial_assignment_batch_{batch_index:02d}",
            prompt=render_prompt(
                "editorial_assignment_review",
                approved_assets=registry,
                ambiguous_shots=[shot_by_id[item] for item in batch_ids],
                candidate_sets=[candidate_by_shot[item] for item in batch_ids],
                neighbour_context=neighbours,
            ),
            output_model=AssignmentBatch,
            request_dir=project / "_requests",
        )
        response_by_id = {item.shot_id: item for item in response.assignments}
        if set(response_by_id) != set(batch_ids):
            missing = sorted(set(batch_ids) - set(response_by_id))
            extra = sorted(set(response_by_id) - set(batch_ids))
            raise EditorialPlanValidationError(
                f"Assignment batch {batch_index} returned the wrong envelope. "
                f"Missing={missing}; extra={extra}."
            )
        for shot_id in batch_ids:
            decision = response_by_id[shot_id]
            _validate_assignment_decision(
                decision,
                shot=shot_by_id[shot_id],
                candidate_set=candidate_by_shot[shot_id],
                assets=assets,
            )
            result[shot_id] = decision
        write_json(
            project
            / "06_shots"
            / f"editorial_assignment_batch_{batch_index:02d}.json",
            response,
        )
    return result


def direct_editorial_shots_compact(
    store: ProjectStore,
    project_id: str,
    *,
    agent_kind: str = "routed",
    consume_response: bool = False,
) -> EditorialShotPlan:
    project = store.project_dir(project_id)
    skeleton = load_model(project / "06_shots/shot_skeleton.json", ShotSkeletonPlan)
    compact_path = project / "06_shots/compact_shot_index.json"
    compact = (
        load_model(compact_path, CompactShotIndex)
        if compact_path.exists()
        else build_compact_shot_index(skeleton)
    )
    master_plan = approved_master_plan(project)
    store.transition(project_id, ProjectState.SHOTS_GENERATING)

    candidate_sets, local, ambiguous = _score_candidates(compact, master_plan)
    write_json(
        project / "06_shots/assignment_candidates.json",
        {
            "project_id": project_id,
            "confidence_threshold": 0.78,
            "margin_threshold": 0.12,
            "candidate_sets": [
                item.model_dump(mode="json") for item in candidate_sets
            ],
        },
    )
    write_json(
        project / "06_shots/local_assignments.json",
        {
            "assignments": [
                item.model_dump(mode="json") for item in local.values()
            ],
            "ambiguous_shot_ids": ambiguous,
        },
    )

    if agent_kind in {"deterministic", "mock"}:
        candidate_by_shot = {item.shot_id: item for item in candidate_sets}
        shot_by_id = {item.shot_id: item for item in compact.shots}
        asset_by_id = {item.asset_id: item for item in master_plan.assets}
        for shot_id in ambiguous:
            candidate = candidate_by_shot[shot_id].candidates[0]
            local[shot_id] = _default_decision(
                shot_by_id[shot_id],
                asset_by_id[candidate.asset_id],
                0,
            )
        reviewed: dict[str, AssignmentDecision] = {}
    else:
        reviewed = _model_assignment_batches(
            store=store,
            project_id=project_id,
            compact=compact,
            master_plan=master_plan,
            candidate_sets=candidate_sets,
            local=local,
            ambiguous_ids=ambiguous,
            agent_kind=agent_kind,
            consume_response=consume_response,
        )

    decisions = {**local, **reviewed}
    asset_by_id = {item.asset_id: item for item in master_plan.assets}
    exceptions = {
        item.shot_id: item for item in master_plan.non_generated_coverage
    }
    shots: list[EditorialShot] = []
    overlays: list[OverlaySpec] = []

    for skeleton_shot in skeleton.shots:
        exception = exceptions.get(skeleton_shot.shot_id)
        if exception:
            overlay = exception.overlay
            if overlay:
                overlays.append(overlay)
            shots.append(
                EditorialShot(
                    shot_id=skeleton_shot.shot_id,
                    chapter_id=skeleton_shot.chapter_id,
                    narration_ids=skeleton_shot.narration_ids,
                    claim_ids=skeleton_shot.claim_ids,
                    start=skeleton_shot.start,
                    end=skeleton_shot.end,
                    duration=skeleton_shot.duration,
                    narration_text=skeleton_shot.narration_text,
                    visual_purpose=skeleton_shot.visual_purpose,
                    story_function=skeleton_shot.story_function,
                    visual_mode=exception.mode,
                    master_asset_id=None,
                    overlay=overlay,
                    archive_source=exception.archive_source,
                    support_reason=exception.reason,
                )
            )
            continue
        decision = decisions.get(skeleton_shot.shot_id)
        if decision is None:
            raise EditorialPlanValidationError(
                f"{skeleton_shot.shot_id} has no final visual assignment."
            )
        asset = asset_by_id[decision.asset_id]
        overlay = None
        if decision.overlay_type:
            if decision.overlay_type not in asset.supported_overlay_families:
                raise EditorialPlanValidationError(
                    f"{skeleton_shot.shot_id} requested unsupported overlay "
                    f"{decision.overlay_type} on {asset.asset_id}."
                )
            overlay = OverlaySpec(
                type=decision.overlay_type,
                template_id=(
                    decision.overlay_template_id
                    or f"{decision.overlay_type}_v1"
                ),
                claim_ids=list(skeleton_shot.claim_ids),
                disclosure=asset.reconstruction_disclosure,
            )
            overlays.append(overlay)
        visual_mode = decision.visual_mode
        if overlay and visual_mode == "master_video":
            visual_mode = "master_video_with_overlay"
        if decision.reuse_operation == "freeze":
            visual_mode = "master_video_freeze"
        shots.append(
            EditorialShot(
                shot_id=skeleton_shot.shot_id,
                chapter_id=skeleton_shot.chapter_id,
                narration_ids=skeleton_shot.narration_ids,
                claim_ids=skeleton_shot.claim_ids,
                start=skeleton_shot.start,
                end=skeleton_shot.end,
                duration=skeleton_shot.duration,
                narration_text=skeleton_shot.narration_text,
                visual_purpose=skeleton_shot.visual_purpose,
                story_function=skeleton_shot.story_function,
                visual_mode=visual_mode,
                master_asset_id=decision.asset_id,
                reuse_operation=decision.reuse_operation,
                crop_id=decision.crop_id,
                playback_speed=decision.playback_speed,
                source_in=decision.source_in,
                source_out=(
                    decision.source_out or asset.source_duration_seconds
                ),
                overlay=overlay,
                support_reason=decision.support_reason,
                transition="hard_cut",
            )
        )

    plan = EditorialShotPlan(
        project_id=skeleton.project_id,
        shots=shots,
        total_seconds=skeleton.total_seconds,
        voiceover_sha256=skeleton.voiceover_sha256,
        master_plan_version=master_plan.plan_version,
        overlay_tracks=overlays,
    )
    validate_editorial_plan(plan, skeleton, master_plan)
    version = store.next_version(project_id, "editorial_shots")
    write_json(
        versioned_path(
            project / "06_shots",
            "editorial_shot_plan",
            ".json",
            version,
        ),
        plan,
    )
    write_json(project / "06_shots/editorial_shot_plan.json", plan)
    write_json(
        project / "06_shots/assignment_summary.json",
        {
            "shot_count": len(skeleton.shots),
            "local_assignment_count": len(local),
            "model_reviewed_assignment_count": len(reviewed),
            "ambiguous_batch_count": math.ceil(
                len(ambiguous) / ASSIGNMENT_BATCH_SIZE
            ),
            "model_reproduced_full_timeline": False,
        },
    )

    legacy = ShotPlan(
        project_id=plan.project_id,
        total_seconds=plan.total_seconds,
        voiceover_sha256=plan.voiceover_sha256,
        shots=[
            Shot(
                shot_id=item.shot_id,
                chapter_id=item.chapter_id,
                narration_ids=item.narration_ids,
                claim_ids=item.claim_ids,
                start=item.start,
                end=item.end,
                duration=item.duration,
                narration_text=item.narration_text,
                visual_purpose=item.visual_purpose,
                story_function=item.story_function,
                factual_scope=item.claim_ids,
                visual_type=item.visual_mode,
                suggested_visual=item.support_reason,
                transition=item.transition,
                overlay_requirements=[item.overlay.type] if item.overlay else [],
                requires_new_master_asset=False,
                candidate_master_asset=item.master_asset_id,
            )
            for item in plan.shots
        ],
    )
    write_json(project / "06_shots/shot_plan.json", legacy)
    write_json(project / "04_shot_plan/shot_plan.json", legacy)
    store.transition(project_id, ProjectState.SHOTS_REVIEW)
    return plan


def validate_response_envelope(
    value: Any,
    output_model: type[BaseModel],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError("Model returned a non-object response.")
    if value.get("error"):
        raise RuntimeError(str(value["error"]))
    required = output_model.model_json_schema().get("required", [])
    missing = [field for field in required if field not in value]
    if missing:
        raise RuntimeError(
            "Model returned the wrong response envelope; missing required field(s): "
            + ", ".join(missing)
        )
    return value


def install_agent_safety_patch() -> None:
    from .agents import RoutedAgent

    if getattr(RoutedAgent, "_compact_planning_safety_installed", False):
        return

    original_execute = RoutedAgent._execute
    original_command_once = RoutedAgent._command_once

    def safe_execute(self, **kwargs):
        value = original_execute(self, **kwargs)
        output_model = kwargs["output_model"]
        request_dir = kwargs["request_dir"]
        stage = kwargs["stage"]
        item = kwargs["item"]
        label = re.sub(
            r"[^a-z0-9]+",
            "_",
            f"{item.get('label', 'attempt')}_{item.get('provider') or item.get('adapter')}",
            flags=re.I,
        ).strip("_").lower()
        write_json(request_dir / f"{stage}_{label}_raw.json", value)
        return validate_response_envelope(value, output_model)

    def safe_command_once(**kwargs):
        value = original_command_once(**kwargs)
        output_path = kwargs["output_path"]
        stage = kwargs["stage"]
        write_json(output_path.parent / f"{stage}_command_raw.json", value)
        if not isinstance(value, dict):
            raise RuntimeError("Command model returned a non-object response.")
        if value.get("error"):
            raise RuntimeError(str(value["error"]))
        return value

    RoutedAgent._execute = safe_execute
    RoutedAgent._command_once = staticmethod(safe_command_once)
    RoutedAgent._compact_planning_safety_installed = True
