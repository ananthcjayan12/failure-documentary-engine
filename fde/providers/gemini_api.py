from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any


def _client():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY is required for Gemini API")
    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError("Install google-genai to use Gemini API") from exc
    return genai.Client(api_key=api_key)


def _extract_json(text: str) -> dict[str, Any]:
    candidates = [text.strip()]
    first, last = text.find("{"), text.rfind("}")
    if first >= 0 and last > first:
        candidates.append(text[first:last + 1])
    errors: list[str] = []
    for candidate in candidates:
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except Exception as exc:
            errors.append(str(exc))
    raise RuntimeError("Gemini returned no JSON object: " + "; ".join(errors[-3:]))


def run_structured(
    *,
    prompt: str,
    schema: dict[str, Any],
    model: str = "gemini-3.5-flash",
    timeout: int = 1200,
    reasoning_effort: str = "high",
) -> dict[str, Any]:
    del timeout
    try:
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("Install google-genai to use Gemini API") from exc
    client = _client()
    thinking_level = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH", "max": "HIGH"}.get(reasoning_effort, "HIGH")
    config_kwargs: dict[str, Any] = {
        "response_mime_type": "application/json",
        "response_schema": schema,
    }
    if model.startswith(("gemini-3", "gemini-2.5")):
        try:
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=thinking_level)
        except Exception:
            pass
    response = client.models.generate_content(
        model=model,
        contents=(
            "Return exactly one JSON object matching the supplied schema. Do not include markdown or commentary.\n\n"
            f"TASK\n{prompt}"
        ),
        config=types.GenerateContentConfig(**config_kwargs),
    )
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, dict):
        return parsed
    text = getattr(response, "text", None)
    if not text:
        raise RuntimeError("Gemini structured generation returned no text")
    return _extract_json(text)


def _part_bytes(part: Any) -> bytes | None:
    inline = getattr(part, "inline_data", None) or getattr(part, "inlineData", None)
    data = getattr(inline, "data", None) if inline is not None else None
    if data is None:
        return None
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return base64.b64decode(data)
    return bytes(data)


def generate_image(
    *,
    prompt: str,
    destination: Path,
    model: str,
    resolution: str = "2K",
    aspect_ratio: str = "16:9",
    quality: str = "standard",
    timeout: int = 1800,
) -> dict[str, Any]:
    del timeout, quality
    try:
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("Install google-genai to use Gemini image generation") from exc
    client = _client()
    destination.parent.mkdir(parents=True, exist_ok=True)
    image_config_kwargs: dict[str, Any] = {"aspect_ratio": aspect_ratio}
    if resolution:
        image_config_kwargs["image_size"] = resolution
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
            image_config=types.ImageConfig(**image_config_kwargs),
        ),
    )
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            payload = _part_bytes(part)
            if payload:
                destination.write_bytes(payload)
                return {
                    "provider": "gemini_api",
                    "model": model,
                    "resolution": resolution,
                    "aspect_ratio": aspect_ratio,
                    "path": str(destination),
                }
    raise RuntimeError("Gemini image generation returned no image data")


def _load_reference(types: Any, reference: Path | None):
    if reference is None:
        return None
    if hasattr(types, "Image") and hasattr(types.Image, "from_file"):
        return types.Image.from_file(location=str(reference))
    return None


def generate_video(
    *,
    prompt: str,
    destination: Path,
    model: str,
    reference: Path | None,
    resolution: str = "720p",
    aspect_ratio: str = "16:9",
    duration: float = 8,
    timeout: int = 7200,
) -> dict[str, Any]:
    try:
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("Install google-genai to use Gemini video generation") from exc
    client = _client()
    destination.parent.mkdir(parents=True, exist_ok=True)
    duration_int = int(round(duration))
    if model.startswith("veo-"):
        duration_int = min((4, 6, 8), key=lambda item: abs(item - duration_int))
    else:
        duration_int = max(3, min(10, duration_int))
    config_kwargs: dict[str, Any] = {
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "duration_seconds": duration_int,
    }
    image = _load_reference(types, reference)
    operation = client.models.generate_videos(
        model=model,
        prompt=prompt,
        image=image,
        config=types.GenerateVideosConfig(**config_kwargs),
    )
    deadline = time.monotonic() + max(1, timeout)
    while not getattr(operation, "done", False):
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Gemini video generation timed out after {timeout}s")
        time.sleep(10)
        operation = client.operations.get(operation)
    error = getattr(operation, "error", None)
    if error:
        raise RuntimeError(f"Gemini video generation failed: {error}")
    response = getattr(operation, "response", None) or getattr(operation, "result", None)
    videos = getattr(response, "generated_videos", None) or getattr(response, "videos", None) or []
    if not videos:
        raise RuntimeError("Gemini video generation returned no video")
    item = videos[0]
    video = getattr(item, "video", item)
    try:
        client.files.download(file=video)
    except Exception:
        pass
    if hasattr(video, "save"):
        video.save(str(destination))
    else:
        data = getattr(video, "video_bytes", None) or getattr(video, "data", None)
        uri = getattr(video, "uri", None)
        if data:
            destination.write_bytes(data if isinstance(data, bytes) else base64.b64decode(data))
        elif uri:
            from urllib.request import urlopen
            with urlopen(uri, timeout=300) as result:
                destination.write_bytes(result.read())
        else:
            raise RuntimeError("Gemini video object cannot be saved")
    return {
        "provider": "gemini_api",
        "model": model,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
        "provider_duration_seconds": duration_int,
        "requested_duration_seconds": duration,
        "path": str(destination),
    }
