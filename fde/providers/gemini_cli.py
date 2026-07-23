from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


def gemini_binary() -> str:
    explicit = os.getenv("FDE_GEMINI_BIN", "").strip()
    binary = explicit or shutil.which("gemini")
    if not binary:
        raise RuntimeError("Gemini CLI was not found. Install @google/gemini-cli and authenticate it.")
    return binary


def _json_object(text: str) -> dict[str, Any]:
    candidates = [text.strip()]
    candidates.extend(re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S | re.I))
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
    raise RuntimeError("Gemini CLI response did not contain one JSON object: " + "; ".join(errors[-3:]))


def _response_text(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if error:
        raise RuntimeError(f"Gemini CLI returned an error: {error}")
    response = payload.get("response")
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        return json.dumps(response, ensure_ascii=False)
    for key in ("result", "content", "text", "message"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
    raise RuntimeError("Gemini CLI JSON envelope contained no response field")


def run_structured(
    *,
    prompt: str,
    schema: dict[str, Any],
    destination: Path,
    cwd: Path,
    model: str = "auto",
    timeout: int = 1800,
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    schema_text = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    full_prompt = (
        "Return exactly one JSON object matching the supplied JSON Schema. "
        "Do not use markdown fences, commentary, tools, or file edits.\n\n"
        f"JSON SCHEMA\n{schema_text}\n\nTASK\n{prompt}"
    )
    # `--model`, `--output-format json`, and `-p` are the stable documented headless flags.
    # Workspace trust and approval defaults stay under the user's Gemini CLI configuration.
    command = [
        gemini_binary(), "--model", model or "auto", "--output-format", "json", "-p", full_prompt,
    ]
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=max(1, timeout),
    )
    combined = (completed.stdout or "") + "\n" + (completed.stderr or "")
    (destination.parent / "gemini-cli-output.log").write_text(combined, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"Gemini CLI failed ({completed.returncode}): {combined[-4000:]}")
    try:
        envelope = json.loads((completed.stdout or "").strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Gemini CLI did not return its documented JSON envelope: {exc}") from exc
    if not isinstance(envelope, dict):
        raise RuntimeError("Gemini CLI JSON output was not an object")
    value = _json_object(_response_text(envelope))
    destination.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return value
