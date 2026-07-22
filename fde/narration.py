from __future__ import annotations

import array
import base64
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path
from typing import Any

from .constants import DOCUMENTARY_PERFORMANCE_TAGS
from .io import load_model, write_json
from .models import AudioChapterRecord, AudioManifest, DocumentaryScript

SAMPLE_RATE = 24_000
CHANNELS = 1
SAMPLE_WIDTH = 2
DEFAULT_CHAPTER_GAP_SECONDS = 0.30
DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-tts-preview"
DEFAULT_GEMINI_VOICE = "Kore"
TAG_PATTERN = re.compile(r"\[([^\[\]]+)\]\s*")
WORD_PATTERN = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)?")

DOCUMENTARY_TTS_DIRECTION = """You are the narrator of a premium failure-investigation documentary.

Read the transcript exactly as written.

The voice should feel authoritative, intimate, restrained, intelligent and cinematic. Speak at a measured natural pace, with clear pronunciation of names, numbers and technical terms. Build suspense through control and silence, never through shouting or exaggerated trailer-style delivery.

Follow bracketed performance tags such as [curious], [serious], [quietly investigative], [thinking pause] and [with restrained urgency]. The tags are performance directions. Do not speak them aloud.

Preserve every spoken word. Do not add, remove, paraphrase or explain anything.

TRANSCRIPT:

"""


def clean_spoken_text(tagged_text: str) -> str:
    return " ".join(TAG_PATTERN.sub("", tagged_text).split())


def performance_tags(tagged_text: str) -> list[str]:
    return [match.strip().lower() for match in TAG_PATTERN.findall(tagged_text)]


def validate_tagged_text(tagged_text: str) -> None:
    tags = performance_tags(tagged_text)
    allowed = set(DOCUMENTARY_PERFORMANCE_TAGS)
    unknown = [tag for tag in tags if tag not in allowed]
    if unknown:
        raise ValueError(f"unsupported documentary performance tag(s): {', '.join(unknown)}")
    if len(tags) > 1:
        raise ValueError("use no more than one performance tag per narration paragraph")
    stripped = tagged_text.lstrip()
    if tags and not stripped.startswith(f"[{tags[0]}]"):
        raise ValueError("performance tags must appear before the complete sentence they control")
    if not clean_spoken_text(tagged_text):
        raise ValueError("narration paragraph contains no spoken text")


def documentary_tts_prompt(tagged_text: str) -> str:
    validate_tagged_text(tagged_text)
    return DOCUMENTARY_TTS_DIRECTION + tagged_text.strip()


def _script_path(project_dir: Path) -> Path:
    primary = project_dir / "03_narration/narration.json"
    legacy = project_dir / "03_script/script.json"
    if primary.exists():
        return primary
    if legacy.exists():
        return legacy
    raise FileNotFoundError("Narration is missing. Generate and approve narration before voice generation.")


def load_narration(project_dir: Path) -> DocumentaryScript:
    return load_model(_script_path(project_dir), DocumentaryScript)


def _cache_key(*, provider: str, model: str, voice: str, tagged_text: str) -> str:
    digest = hashlib.sha256()
    for value in (provider, model, voice, DOCUMENTARY_TTS_DIRECTION, tagged_text, str(SAMPLE_RATE), "pcm_s16le"):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _duration_from_text(text: str) -> float:
    words = max(1, len(WORD_PATTERN.findall(text)))
    return max(0.75, words / 138.0 * 60.0)


def _mock_wav(path: Path, clean_text: str) -> dict[str, Any]:
    duration = _duration_from_text(clean_text)
    frame_count = max(1, round(duration * SAMPLE_RATE))
    samples = array.array("h")
    for frame in range(frame_count):
        t = frame / SAMPLE_RATE
        envelope = min(1.0, t / 0.05, max(0.0, (duration - t) / 0.08))
        syllabic = 0.55 + 0.45 * math.sin(2 * math.pi * 3.1 * t) ** 2
        value = int(1500 * envelope * syllabic * math.sin(2 * math.pi * 176 * t))
        samples.append(value)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(CHANNELS)
        handle.setsampwidth(SAMPLE_WIDTH)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(samples.tobytes())
    words = WORD_PATTERN.findall(clean_text)
    slot = duration / max(1, len(words))
    alignment = [
        {
            "word": word,
            "start": round(index * slot, 3),
            "end": round(min(duration, (index + 0.84) * slot), 3),
            "confidence": 1.0,
        }
        for index, word in enumerate(words)
    ]
    return {"provider": "mock", "native_word_alignment": alignment}


def _extract_gemini_audio(response: Any) -> bytes:
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            inline = getattr(part, "inline_data", None) or getattr(part, "inlineData", None)
            data = getattr(inline, "data", None) if inline is not None else None
            if data is None:
                continue
            if isinstance(data, bytes):
                return data
            if isinstance(data, str):
                return base64.b64decode(data)
            return bytes(data)
    raise RuntimeError("Gemini TTS returned no inline audio data")


def _write_pcm_or_wav(path: Path, payload: bytes) -> None:
    if payload.startswith(b"RIFF"):
        path.write_bytes(payload)
        return
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(CHANNELS)
        handle.setsampwidth(SAMPLE_WIDTH)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(payload)


def _gemini_wav(path: Path, tagged_text: str, model: str, voice: str) -> dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY is required for Gemini TTS")
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("Install google-genai to use Gemini TTS") from exc
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=documentary_tts_prompt(tagged_text),
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                )
            ),
        ),
    )
    _write_pcm_or_wav(path, _extract_gemini_audio(response))
    return {"provider": "gemini", "model": model, "voice": voice}


def _ffmpeg_to_wav(source: Path, destination: Path) -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required to normalize generated speech")
    completed = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(source), "-ar", str(SAMPLE_RATE), "-ac", "1",
            "-c:a", "pcm_s16le", str(destination),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout)[-3000:])


def _elevenlabs_wav(path: Path, tagged_text: str, model: str, voice: str) -> dict[str, Any]:
    api_key = os.getenv("ELEVENLABS_API_KEY") or os.getenv("XI_API_KEY")
    if not api_key or not voice:
        raise RuntimeError("ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID are required")
    query = urllib.parse.urlencode({"output_format": "mp3_44100_128"})
    request = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?{query}",
        data=json.dumps({"text": tagged_text, "model_id": model}).encode("utf-8"),
        headers={"xi-api-key": api_key, "accept": "audio/mpeg", "content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=240) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ElevenLabs TTS failed with HTTP {exc.code}: {detail}") from exc
    source = path.with_suffix(".source.mp3")
    source.write_bytes(payload)
    _ffmpeg_to_wav(source, path)
    return {"provider": "elevenlabs", "model": model, "voice": voice}


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / handle.getframerate()


def _quality(path: Path) -> dict[str, float | str]:
    with wave.open(str(path), "rb") as handle:
        if (handle.getnchannels(), handle.getsampwidth(), handle.getframerate()) != (CHANNELS, SAMPLE_WIDTH, SAMPLE_RATE):
            raise RuntimeError(f"unexpected chapter audio format: {path}")
        frames = handle.readframes(handle.getnframes())
        duration = handle.getnframes() / handle.getframerate()
    samples = array.array("h")
    samples.frombytes(frames)
    if not samples:
        raise RuntimeError(f"chapter audio contains no samples: {path}")
    peak = max(abs(value) for value in samples)
    rms = math.sqrt(sum(value * value for value in samples) / len(samples))
    rms_dbfs = 20 * math.log10(max(rms, 1.0) / 32768)
    clipping_ratio = sum(abs(value) >= 32760 for value in samples) / len(samples)
    status = "passed" if duration >= 0.2 and rms_dbfs > -55 and clipping_ratio < 0.01 else "failed"
    report: dict[str, float | str] = {
        "status": status,
        "duration": round(duration, 3),
        "peak": float(peak),
        "rms_dbfs": round(rms_dbfs, 2),
        "clipping_ratio": round(clipping_ratio, 6),
    }
    if status != "passed":
        raise RuntimeError(f"chapter audio quality gate failed: {report}")
    return report


def _silence(path: Path, seconds: float) -> None:
    frames = max(0, round(seconds * SAMPLE_RATE))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(CHANNELS)
        handle.setsampwidth(SAMPLE_WIDTH)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(b"\0" * frames * SAMPLE_WIDTH)


def _assemble_wav(parts: list[Path], target: Path) -> None:
    with wave.open(str(target), "wb") as output:
        output.setnchannels(CHANNELS)
        output.setsampwidth(SAMPLE_WIDTH)
        output.setframerate(SAMPLE_RATE)
        for part in parts:
            with wave.open(str(part), "rb") as source:
                if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (CHANNELS, SAMPLE_WIDTH, SAMPLE_RATE):
                    raise RuntimeError(f"audio format mismatch: {part}")
                output.writeframes(source.readframes(source.getnframes()))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _make_mp3(source: Path, target: Path) -> bool:
    if not shutil.which("ffmpeg"):
        return False
    completed = subprocess.run(
        ["ffmpeg", "-y", "-i", str(source), "-c:a", "libmp3lame", "-b:a", "160k", str(target)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout)[-3000:])
    return True


def generate_voice(
    project_dir: Path,
    *,
    provider: str = "gemini",
    model: str | None = None,
    voice: str | None = None,
    paragraph_ids: list[str] | None = None,
    force: bool = False,
    chapter_gap_seconds: float = DEFAULT_CHAPTER_GAP_SECONDS,
) -> AudioManifest:
    project_dir = Path(project_dir)
    script = load_narration(project_dir)
    provider = provider.strip().lower()
    model = model or (
        DEFAULT_GEMINI_MODEL if provider == "gemini" else os.getenv("ELEVENLABS_MODEL_ID", "eleven_v3")
        if provider == "elevenlabs" else "deterministic-mock"
    )
    voice = voice or (
        os.getenv("GEMINI_TTS_VOICE", DEFAULT_GEMINI_VOICE) if provider == "gemini"
        else os.getenv("ELEVENLABS_VOICE_ID", "") if provider == "elevenlabs" else "mock-narrator"
    )
    wanted = set(paragraph_ids or [])
    root = project_dir / "04_voice"
    chapter_root = root / "chapters"
    chapter_root.mkdir(parents=True, exist_ok=True)
    assembly: list[Path] = []
    records: list[AudioChapterRecord] = []
    absolute = 0.0

    for index, segment in enumerate(script.segments):
        paragraph_id = segment.narration_id
        validate_tagged_text(segment.text)
        tagged = segment.text.strip()
        clean = clean_spoken_text(tagged)
        chapter_dir = chapter_root / paragraph_id
        chapter_dir.mkdir(parents=True, exist_ok=True)
        (chapter_dir / "tagged_text.txt").write_text(tagged + "\n", encoding="utf-8")
        (chapter_dir / "clean_text.txt").write_text(clean + "\n", encoding="utf-8")
        key = _cache_key(provider=provider, model=model, voice=voice, tagged_text=tagged)
        key_path = chapter_dir / "cache_key.txt"
        wav_path = chapter_dir / "audio.wav"
        selected = not wanted or paragraph_id in wanted
        reused = wav_path.exists() and key_path.exists() and key_path.read_text(encoding="utf-8").strip() == key
        generation: dict[str, Any] = {"provider": provider, "model": model, "voice": voice}
        if selected and (force or not reused):
            if provider == "mock":
                generation = _mock_wav(wav_path, clean)
            elif provider == "gemini":
                generation = _gemini_wav(wav_path, tagged, model, voice)
            elif provider == "elevenlabs":
                generation = _elevenlabs_wav(wav_path, tagged, model, voice)
            else:
                raise ValueError("voice provider must be gemini, elevenlabs, or mock")
            key_path.write_text(key + "\n", encoding="utf-8")
            write_json(chapter_dir / "generation.json", generation)
            if generation.get("native_word_alignment"):
                write_json(chapter_dir / "alignment.json", {"words": generation["native_word_alignment"]})
            reused = False
        elif not wav_path.exists():
            raise RuntimeError(f"voice chapter {paragraph_id} is missing; include it in the requested paragraph IDs")
        quality = _quality(wav_path)
        write_json(chapter_dir / "quality.json", quality)
        duration = _wav_duration(wav_path)
        trailing = chapter_gap_seconds if index + 1 < len(script.segments) else 0.0
        alignment_path = chapter_dir / "alignment.json"
        records.append(
            AudioChapterRecord(
                paragraph_id=paragraph_id,
                tagged_text=tagged,
                clean_text=clean,
                path=str(wav_path.relative_to(project_dir)),
                cache_key=key,
                cache_reused=reused,
                absolute_start=round(absolute, 3),
                speech_duration=round(duration, 3),
                trailing_pause=round(trailing, 3),
                absolute_end=round(absolute + duration + trailing, 3),
                quality=quality,
                alignment_path=str(alignment_path.relative_to(project_dir)) if alignment_path.exists() else None,
            )
        )
        assembly.append(wav_path)
        if trailing:
            pause = chapter_root / f"pause_{index + 1:03d}.wav"
            _silence(pause, trailing)
            assembly.append(pause)
        absolute += duration + trailing

    master_wav = root / "voiceover_master.wav"
    _assemble_wav(assembly, master_wav)
    mp3_path = root / "voiceover.mp3"
    made_mp3 = _make_mp3(master_wav, mp3_path)
    manifest = AudioManifest(
        project_id=script.project_id,
        provider=provider,
        model_id=model,
        voice_id=voice,
        chapter_gap_seconds=chapter_gap_seconds,
        duration_seconds=round(absolute, 3),
        voiceover_wav=str(master_wav.relative_to(project_dir)),
        voiceover_mp3=str(mp3_path.relative_to(project_dir)) if made_mp3 else None,
        voiceover_sha256=_sha256(master_wav),
        chapters=records,
    )
    write_json(root / "audio_manifest.json", manifest)
    write_json(root / "audio_generation.json", {
        "provider": provider,
        "model": model,
        "voice": voice,
        "duration_seconds": manifest.duration_seconds,
        "voiceover_sha256": manifest.voiceover_sha256,
        "chapter_count": len(records),
        "mp3_created": made_mp3,
    })
    return manifest
