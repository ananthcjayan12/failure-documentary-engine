from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

API_URL = "https://api.moonshot.ai/v1/chat/completions"


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
    raise RuntimeError("Kimi returned no JSON object: " + "; ".join(errors[-3:]))


def run_structured(
    *,
    prompt: str,
    schema: dict[str, Any],
    model: str = "kimi-k3",
    timeout: int = 1200,
    reasoning_effort: str = "high",
) -> dict[str, Any]:
    api_key = os.getenv("MOONSHOT_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("MOONSHOT_API_KEY is required for Kimi API")
    schema_text = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Return exactly one JSON object. It must validate against the JSON Schema supplied by the user. "
                    "Do not use markdown fences, commentary, or trailing text."
                ),
            },
            {"role": "user", "content": f"JSON SCHEMA\n{schema_text}\n\nTASK\n{prompt}"},
        ],
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    if model == "kimi-k3":
        payload["reasoning_effort"] = reasoning_effort if reasoning_effort in {"low", "high", "max"} else "high"
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
        raise RuntimeError(f"Kimi API failed with HTTP {exc.code}: {detail}") from exc
    try:
        content = value["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Kimi API returned an unexpected response: {value}") from exc
    if isinstance(content, dict):
        return content
    return _extract_json(str(content))
