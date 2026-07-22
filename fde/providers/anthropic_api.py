from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
_UNSUPPORTED_SCHEMA_CONSTRAINTS = frozenset({
    "exclusiveMaximum",
    "exclusiveMinimum",
    "maxLength",
    "maximum",
    "minLength",
    "minimum",
    "multipleOf",
    "pattern",
})


def _strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Make a JSON Schema acceptable to Claude's strict structured output API.

    Claude requires every object schema, including objects nested in arrays or
    definitions, to explicitly disallow undeclared properties. Its structured
    output grammar also does not support Pydantic's numeric and string
    constraints. The original Pydantic model remains the final validator, so
    those constraints are still enforced after Claude responds.
    """
    normalized = deepcopy(schema)

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("type") == "object":
                value["additionalProperties"] = False
            for key in _UNSUPPORTED_SCHEMA_CONSTRAINTS:
                value.pop(key, None)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(normalized)
    return normalized


def run_structured(
    *, prompt: str, schema: dict[str, Any], model: str, timeout: int,
    reasoning_effort: str = "medium",
) -> dict[str, Any]:
    """Call Claude's Messages API and return a schema-constrained JSON object.

    Claude Sonnet 5 does not accept the Messages API ``temperature`` parameter.
    Its request controls here are the required ``max_tokens`` plus
    ``output_config.effort`` and ``output_config.format``.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")

    payload = {
        "model": model or "claude-sonnet-5",
        "max_tokens": 16000,
        "messages": [{"role": "user", "content": prompt}],
        "output_config": {
            "effort": reasoning_effort if reasoning_effort in {"low", "medium", "high"} else "medium",
            "format": {"type": "json_schema", "schema": _strict_json_schema(schema)},
        },
    }
    request = Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
            "x-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=max(1, timeout)) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[-4000:]
        raise RuntimeError(f"Claude API request failed ({exc.code}): {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Claude API request failed: {exc.reason}") from exc

    text = "".join(
        block.get("text", "")
        for block in result.get("content", [])
        if block.get("type") == "text"
    ).strip()
    if not text:
        raise RuntimeError("Claude API returned no text content")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Claude API returned invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Claude API structured response must be a JSON object")
    return value
