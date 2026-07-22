from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

from .io import load_model, read_json, write_json
from .models import AudioManifest, AudioTiming, DocumentaryScript, ParagraphTiming, WordTiming
from .narration import clean_spoken_text

WORD_PATTERN = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)?")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _script(project_dir: Path) -> DocumentaryScript:
    path = project_dir / "03_narration/narration.json"
    if not path.exists():
        path = project_dir / "03_script/script.json"
    return load_model(path, DocumentaryScript)


def _native_words(project_dir: Path, chapter: Any) -> list[dict[str, Any]] | None:
    if not chapter.alignment_path:
        return None
    path = project_dir / chapter.alignment_path
    if not path.exists():
        return None
    payload = read_json(path)
    words = payload.get("words") if isinstance(payload, dict) else None
    return words if isinstance(words, list) and words else None


def _whisper_words(path: Path) -> list[dict[str, Any]]:
    try:
        import whisper
    except ImportError as exc:
        raise RuntimeError(
            "Word timing requires native provider alignment or openai-whisper. "
            "Install openai-whisper, or use the mock voice provider for offline tests."
        ) from exc
    model_name = os.getenv("FDE_WHISPER_MODEL", "base.en")
    language = os.getenv("FDE_WHISPER_LANGUAGE", "en").strip() or None
    model = whisper.load_model(model_name)
    options: dict[str, Any] = {"word_timestamps": True, "fp16": False, "verbose": False}
    if language:
        options["language"] = language
    result = model.transcribe(str(path), **options)
    words: list[dict[str, Any]] = []
    for segment in result.get("segments", []) or []:
        for item in segment.get("words", []) or []:
            raw = str(item.get("word") or "").strip()
            tokens = WORD_PATTERN.findall(raw)
            if not tokens or item.get("start") is None or item.get("end") is None:
                continue
            for token in tokens:
                words.append({
                    "word": token,
                    "start": float(item["start"]),
                    "end": float(item["end"]),
                    "confidence": item.get("probability"),
                })
    if not words:
        raise RuntimeError(f"Whisper produced no word timestamps for {path}")
    return words


def _proportional_words(clean_text: str, duration: float) -> list[dict[str, Any]]:
    tokens = WORD_PATTERN.findall(clean_text)
    if not tokens:
        raise RuntimeError("narration paragraph contains no alignable words")
    slot = duration / len(tokens)
    return [
        {
            "word": token,
            "start": index * slot,
            "end": min(duration, (index + 0.85) * slot),
            "confidence": None,
        }
        for index, token in enumerate(tokens)
    ]


def derive_timing(project_dir: Path, *, allow_approximate: bool | None = None) -> AudioTiming:
    project_dir = Path(project_dir)
    script = _script(project_dir)
    manifest = load_model(project_dir / "04_voice/audio_manifest.json", AudioManifest)
    voiceover = project_dir / manifest.voiceover_wav
    measured_hash = _sha256(voiceover)
    if measured_hash != manifest.voiceover_sha256:
        raise RuntimeError("voiceover changed after audio_manifest.json was created")
    allow_approximate = (
        os.getenv("FDE_ALLOW_APPROXIMATE_TIMING", "0").lower() in {"1", "true", "yes"}
        if allow_approximate is None else allow_approximate
    )
    segment_by_id = {item.narration_id: item for item in script.segments}
    paragraphs: list[ParagraphTiming] = []
    words: list[WordTiming] = []
    sources: set[str] = set()
    exact = True
    for chapter in manifest.chapters:
        segment = segment_by_id.get(chapter.paragraph_id)
        if segment is None:
            raise RuntimeError(f"audio chapter {chapter.paragraph_id} has no matching narration paragraph")
        local = _native_words(project_dir, chapter)
        if local:
            sources.add("native_provider_alignment")
        else:
            try:
                local = _whisper_words(project_dir / chapter.path)
                sources.add("openai_whisper_word_timestamps")
            except RuntimeError:
                if not allow_approximate:
                    raise
                local = _proportional_words(clean_spoken_text(segment.text), chapter.speech_duration)
                sources.add("proportional_fallback")
                exact = False
        start = float(chapter.absolute_start)
        for item in local:
            word_start = round(start + float(item["start"]), 3)
            word_end = round(start + float(item["end"]), 3)
            words.append(
                WordTiming(
                    index=len(words),
                    paragraph_id=chapter.paragraph_id,
                    word=str(item["word"]),
                    start=word_start,
                    end=max(word_start, word_end),
                    confidence=item.get("confidence"),
                )
            )
        paragraphs.append(
            ParagraphTiming(
                paragraph_id=chapter.paragraph_id,
                start=round(chapter.absolute_start, 3),
                end=round(chapter.absolute_end, 3),
                duration=round(chapter.absolute_end - chapter.absolute_start, 3),
            )
        )
    source = "+".join(sorted(sources))
    timing = AudioTiming(
        project_id=script.project_id,
        source=source,
        exact=exact,
        voiceover_sha256=measured_hash,
        audio_duration_seconds=manifest.duration_seconds,
        paragraphs=paragraphs,
        words=words,
    )
    root = project_dir / "05_timing"
    write_json(root / "audio_timing.json", timing)
    write_json(root / "word_timestamps.json", {
        "project_id": timing.project_id,
        "source": timing.source,
        "exact": timing.exact,
        "voiceover_sha256": timing.voiceover_sha256,
        "audio_duration_seconds": timing.audio_duration_seconds,
        "words": [item.model_dump(mode="json") for item in timing.words],
    })
    return timing


def timing_is_current(project_dir: Path) -> bool:
    try:
        manifest = load_model(project_dir / "04_voice/audio_manifest.json", AudioManifest)
        timing = load_model(project_dir / "05_timing/audio_timing.json", AudioTiming)
        voiceover = project_dir / manifest.voiceover_wav
        return (
            voiceover.exists()
            and _sha256(voiceover) == manifest.voiceover_sha256 == timing.voiceover_sha256
            and bool(timing.words)
        )
    except Exception:
        return False
