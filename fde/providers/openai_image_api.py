from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

API_URL = "https://api.openai.com/v1/images/generations"


def generate_image(
    *,
    prompt: str,
    destination: Path,
    model: str = "gpt-image-2",
    resolution: str = "1536x1024",
    quality: str = "high",
    timeout: int = 1800,
) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for GPT Image API")
    payload = {
        "model": model,
        "prompt": prompt,
        "size": resolution or "auto",
        "quality": quality or "auto",
        "n": 1,
        "response_format": "b64_json",
    }
    request = Request(
        API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=max(1, timeout)) as response:
            value = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI image generation failed with HTTP {exc.code}: {detail}") from exc
    try:
        item: dict[str, Any] = value["data"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"OpenAI image API returned an unexpected response: {value}") from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    if item.get("b64_json"):
        destination.write_bytes(base64.b64decode(item["b64_json"]))
        source = "base64"
    elif item.get("url"):
        with urlopen(item["url"], timeout=300) as response:
            destination.write_bytes(response.read())
        source = item["url"]
    else:
        raise RuntimeError("OpenAI image API returned neither b64_json nor URL")
    return {
        "provider": "openai_image_api",
        "model": model,
        "quality": quality,
        "resolution": resolution,
        "source": source,
        "path": str(destination),
    }
