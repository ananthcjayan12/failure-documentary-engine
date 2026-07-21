from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any, Iterable

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}


def grok_binary() -> str:
    explicit = os.getenv("FDE_GROK_BIN", "").strip()
    binary = explicit or shutil.which("grok")
    if not binary:
        raise RuntimeError("Grok Build CLI was not found. Install it and run `grok login`.")
    return binary


def _media_files(roots: Iterable[Path], extensions: set[str], since: float = 0.0) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for root in roots:
        if not root.exists():
            continue
        try:
            for path in root.rglob("*"):
                try:
                    if path.is_file() and path.suffix.lower() in extensions and path.stat().st_mtime >= since:
                        found[str(path.resolve())] = path
                except (OSError, PermissionError):
                    continue
        except (OSError, PermissionError):
            continue
    return found


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)


def _extract_candidates(output: str, extensions: set[str]) -> list[str]:
    candidates: list[str] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
            for value in _strings(parsed):
                if any(ext in value.lower() for ext in extensions):
                    candidates.append(value)
        except json.JSONDecodeError:
            candidates.extend(
                re.findall(
                    r"(?:https?://\S+|(?:/|~)[^\s\"']+\.(?:png|jpe?g|webp|mp4|mov|webm|m4v))",
                    line,
                    flags=re.I,
                )
            )
    return candidates


def streaming_text(output: str) -> str:
    chunks: list[str] = []
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            chunks.append(line)
            continue
        if isinstance(event, dict) and event.get("type") in {"text", "thought", "error"}:
            data = event.get("data")
            if isinstance(data, str):
                chunks.append(data)
    return "".join(chunks)


def _materialize_candidate(candidate: str, destination: Path) -> bool:
    cleaned = candidate.strip("'\"),.;")
    if cleaned.startswith(("http://", "https://")):
        try:
            with urllib.request.urlopen(cleaned, timeout=180) as response:
                destination.write_bytes(response.read())
            return True
        except Exception:
            return False
    path = Path(cleaned).expanduser()
    if path.exists() and path.is_file():
        shutil.copy2(path, destination)
        return True
    return False


def _base_command(*, prompt: str, cwd: Path, model: str, max_turns: int = 24) -> list[str]:
    command = [
        grok_binary(),
        "--no-auto-update",
        "-p",
        prompt,
        "--output-format",
        "streaming-json",
        "--cwd",
        str(cwd),
        "--always-approve",
        "--sandbox",
        "workspace",
        "--max-turns",
        str(max_turns),
        "--no-plan",
        "--no-subagents",
        "--no-memory",
        "--disable-web-search",
    ]
    if model and model not in {"authenticated-default", "default"}:
        command[1:1] = ["--model", model]
    return command


def run_structured(
    *, prompt: str, schema: dict[str, Any], destination: Path, cwd: Path,
    model: str = "authenticated-default", timeout: int = 1800,
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    schema_text = json.dumps(schema, ensure_ascii=False)
    full_prompt = (
        "Complete this task and return exactly one JSON object matching the supplied JSON Schema. "
        "Do not call media tools, edit files, inspect credentials, or wrap the result in markdown.\n\n"
        f"JSON SCHEMA\n{schema_text}\n\nTASK\n{prompt}"
    )
    result = subprocess.run(
        _base_command(prompt=full_prompt, cwd=cwd, model=model, max_turns=16),
        capture_output=True,
        text=True,
        timeout=max(1, timeout),
    )
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    (destination.parent / "grok-cli-output.jsonl").write_text(combined, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"Grok structured generation failed: {combined[-4000:]}")
    text = streaming_text(combined).strip()
    parsed = _extract_json_object(text)
    destination.write_text(json.dumps(parsed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return parsed


def _extract_json_object(text: str) -> dict[str, Any]:
    candidates = [text]
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S | re.I)
    candidates.extend(fenced)
    first, last = text.find("{"), text.rfind("}")
    if first >= 0 and last > first:
        candidates.append(text[first:last + 1])
    failures: list[str] = []
    for candidate in candidates:
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except Exception as exc:
            failures.append(str(exc))
    raise RuntimeError("Grok returned no valid JSON object: " + "; ".join(failures[-3:]))


def generate_media(
    *, prompt: str, destination: Path, media_type: str, cwd: Path,
    reference: Path | None = None, model: str = "authenticated-default",
    timeout: int = 3600, duration: float = 5, aspect_ratio: str = "16:9",
) -> dict[str, Any]:
    if media_type not in {"image", "video"}:
        raise ValueError(f"Unsupported Grok media type: {media_type}")
    extensions = IMAGE_EXTENSIONS if media_type == "image" else VIDEO_EXTENSIONS
    destination.parent.mkdir(parents=True, exist_ok=True)
    start = time.time() - 1
    scan_roots = [cwd, Path.home() / ".grok"]
    before = _media_files(scan_roots, extensions)
    reference_rule = (
        f"\nUse this exact approved reference image as the image-to-video source: {reference.resolve()}"
        if reference else ""
    )
    tool_rule = (
        "Use the built-in Imagine image-generation tool exactly once."
        if media_type == "image"
        else "Use the built-in Imagine image-to-video tool exactly once."
    )
    full_prompt = (
        f"{tool_rule}\n"
        "Do not edit code and do not create substitute placeholder media. "
        "Wait for the media task to finish, then return the exact local output path or output URL. "
        "If the media tool fails, report that error immediately; do not inspect configuration, credentials, "
        "source code, environment variables, or unrelated files.\n"
        f"Required aspect ratio: {aspect_ratio}. Required duration for video: {duration:.1f} seconds."
        f"{reference_rule}\n\nCREATIVE BRIEF\n{prompt}"
    )
    command = _base_command(prompt=full_prompt, cwd=cwd, model=model, max_turns=24)
    result = subprocess.run(command, capture_output=True, text=True, timeout=max(1, timeout))
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    (destination.parent / "grok-cli-output.jsonl").write_text(combined, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"Grok media generation failed: {combined[-4000:]}")
    for candidate in _extract_candidates(combined, extensions):
        if _materialize_candidate(candidate, destination):
            return {"provider": "grok_cli", "model": model, "source": candidate, "path": str(destination)}
    after = _media_files(scan_roots, extensions, since=start)
    new_paths = [path for key, path in after.items() if key not in before]
    if new_paths:
        newest = max(new_paths, key=lambda path: path.stat().st_mtime)
        shutil.copy2(newest, destination)
        return {"provider": "grok_cli", "model": model, "source": str(newest), "path": str(destination)}
    transcript = streaming_text(combined)
    if "ZDR" in transcript and "upload_url" in transcript:
        raise RuntimeError(
            "Grok CLI video output is blocked by the account's Zero Data Retention configuration. "
            "Configure tools.zdr_video_output_s3 in ~/.grok/config.toml or use a manual/API fallback."
        )
    raise RuntimeError(
        "Grok completed but no generated media path or URL was found. Run `grok` interactively once, "
        "confirm Imagine tools are enabled, and retry. Raw output was preserved."
    )
