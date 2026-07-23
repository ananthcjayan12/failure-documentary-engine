from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..io import read_json, write_json
from ..orchestrator import resolve_task
from .restart import RESTART_SPECS, restart_stage


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


ACTION_COMMANDS: dict[str, list[str]] = {
    "research": ["research", "{project}", "--agent", "{agent}"],
    "structure": ["structure", "{project}", "--agent", "{agent}"],
    "narration": ["narration", "{project}", "--agent", "{agent}"],
    "script": ["narration", "{project}", "--agent", "{agent}"],
    "consume_research": ["research", "{project}", "--agent", "manual", "--consume-response"],
    "consume_structure": ["structure", "{project}", "--agent", "manual", "--consume-response"],
    "consume_narration": ["narration", "{project}", "--agent", "manual", "--consume-response"],
    "consume_script": ["narration", "{project}", "--agent", "manual", "--consume-response"],
    "generate_voice": ["generate-voice", "{project}"],
    "generate_timing": ["generate-timing", "{project}"],
    # Preserve the orchestrator-selected visual-director agent.  Without this
    # placeholder the Studio resolves Claude/Codex/etc., but the CLI receives
    # no --agent argument and silently falls back to its deterministic default.
    "shots": ["shots", "{project}", "--agent", "{agent}"],
    "prepare_images": ["prepare-images", "{project}"],
    "generate_images": ["generate-images", "{project}"],
    "approve_images": ["approve-images", "{project}"],
    "render_animatic": ["render-animatic", "{project}"],
    "approve_animatic": ["approve-animatic", "{project}"],
    "prepare_videos": ["prepare-videos", "{project}"],
    "generate_videos": ["generate-videos", "{project}"],
    "approve_videos": ["approve-videos", "{project}"],
    "render_final_preview": ["render-final-preview", "{project}"],
}

ACTION_TASKS: dict[str, str] = {
    "research": "research",
    "structure": "structure",
    "narration": "narration_writer",
    "script": "narration_writer",
    "generate_voice": "voice_generator",
    "generate_timing": "word_alignment",
    "shots": "shot_planner",
    "prepare_images": "image_prompt_writer",
    "generate_images": "image_generator",
    "render_animatic": "animatic_renderer",
    "prepare_videos": "video_prompt_writer",
    "generate_videos": "video_generator",
    "render_final_preview": "final_renderer",
}


def _voice_provider(route: dict[str, Any] | None, config: dict[str, Any]) -> str:
    if config.get("agent_mode") == "mock" or (route or {}).get("provider") == "mock":
        return "mock"
    provider = str((route or {}).get("provider") or "google_tts").lower()
    if provider == "manual_upload":
        return "manual"
    if "eleven" in provider:
        return "elevenlabs"
    return "gemini"


def _restart_request(action: str) -> tuple[str, bool] | None:
    for prefix, run_again in (("restart_", False), ("rerun_", True)):
        if action.startswith(prefix):
            stage_id = action[len(prefix):]
            if stage_id in RESTART_SPECS:
                return stage_id, run_again
    return None


class JobManager:
    def __init__(self, workspace: Path, config_getter, orchestrator_getter=None, store=None) -> None:
        self.workspace = Path(workspace).resolve()
        self.config_getter = config_getter
        self.orchestrator_getter = orchestrator_getter
        self.store = store
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._lock = threading.Lock()
        self._reconcile_stale_jobs()

    def state_path(self, project_id: str) -> Path:
        return self.workspace / project_id / "studio_run.json"

    def log_path(self, project_id: str) -> Path:
        return self.workspace / project_id / "studio.log"

    def state(self, project_id: str) -> dict[str, Any]:
        path = self.state_path(project_id)
        payload: dict[str, Any] = {}
        if path.exists():
            try:
                payload = read_json(path)
            except Exception:
                payload = {}
        process = self._processes.get(project_id)
        if process and process.poll() is None:
            payload["status"] = "running"
            payload["pid"] = process.pid
        return {
            "status": payload.get("status", "idle"), "action": payload.get("action"),
            "label": payload.get("label"), "started_at": payload.get("started_at"),
            "ended_at": payload.get("ended_at"), "return_code": payload.get("return_code"),
            "error": payload.get("error"), "pid": payload.get("pid"), "routing": payload.get("routing"),
            "restart": payload.get("restart"),
        }

    def log_tail(self, project_id: str, lines: int = 160) -> str:
        path = self.log_path(project_id)
        if not path.exists():
            return ""
        data = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(data[-max(1, min(lines, 1000)):])

    def start(self, project_id: str, action: str, *, agent: str | None = None) -> dict[str, Any]:
        restart_request = _restart_request(action)
        if not restart_request and action not in ACTION_COMMANDS:
            raise ValueError(f"Unknown action: {action}")
        with self._lock:
            running = self._processes.get(project_id)
            if running and running.poll() is None:
                raise RuntimeError("A job is already running for this project")
            restart_report = None
            if restart_request:
                if self.store is None:
                    raise RuntimeError("Stage restart requires a project store")
                stage_id, run_again = restart_request
                restart_report = restart_stage(self.store, project_id, stage_id)
                if not run_again:
                    state = {
                        "status": "completed", "action": action,
                        "label": f"Restart {stage_id.replace('_', ' ').title()}",
                        "started_at": utc_now(), "ended_at": utc_now(), "return_code": 0,
                        "error": None, "pid": None, "routing": None, "restart": restart_report,
                    }
                    write_json(self.state_path(project_id), state)
                    return state
                action = restart_report["run_action"]
            config = self.config_getter()
            task_id = ACTION_TASKS.get(action)
            route = None
            if task_id and self.orchestrator_getter is not None:
                context: dict[str, Any] = {}
                if self.store is not None:
                    try:
                        brief = self.store.brief(project_id)
                        context = {"duration_seconds": brief.target_duration_seconds, "topic": brief.topic, "title": brief.title}
                    except Exception:
                        context = {}
                route = resolve_task(self.orchestrator_getter(), task_id, context)
            command_template = ACTION_COMMANDS[action]
            accepts_agent = any("{agent}" in part for part in command_template)
            if action.startswith("consume_"):
                selected_agent = "manual"
            elif agent:
                selected_agent = agent
            elif config.get("agent_mode") == "mock" and accepts_agent:
                selected_agent = "mock"
            elif route and accepts_agent:
                mode = route.get("provider_mode")
                selected_agent = "manual" if mode == "manual" else "mock" if mode == "mock" else "routed"
            else:
                selected_agent = config.get("agent_mode", "manual")
            command_parts = [part.format(project=project_id, agent=selected_agent) for part in command_template]
            if action == "generate_voice":
                voice_provider = _voice_provider(route, config)
                if voice_provider == "manual":
                    raise RuntimeError("Manual Upload is selected for voice. Upload a WAV in the Voice stage instead of running generation.")
                command_parts.extend(["--provider", voice_provider])
                if route:
                    if route.get("model"):
                        command_parts.extend(["--model", str(route["model"])])
                    if route.get("voice"):
                        command_parts.extend(["--voice", str(route["voice"])])
            command = [sys.executable, "-m", "fde", *command_parts, "--workspace", str(self.workspace)]
            env = os.environ.copy()
            if route:
                env["FDE_LLM_COMMAND"] = str(route.get("command_template") or config.get("command_template") or "")
                env["FDE_LLM_MODEL"] = str(route.get("model", ""))
                env["FDE_LLM_PROVIDER"] = str(route.get("provider", ""))
                env["FDE_LLM_REASONING"] = str(route.get("reasoning_effort", "medium"))
                env["FDE_LLM_TEMPERATURE"] = str(route.get("temperature", 0.2))
                env["FDE_LLM_TIMEOUT"] = str(route.get("timeout_seconds", 900))
                env["FDE_LLM_RETRIES"] = str(route.get("retry_count", 0))
                env["FDE_LLM_FALLBACK_COMMAND"] = str(route.get("fallback_command_template", ""))
                env["FDE_LLM_FALLBACK_MODEL"] = str(route.get("fallback_model", ""))
                env["FDE_LLM_FALLBACK_PROVIDER"] = str(route.get("fallback_provider", ""))
                env["FDE_LLM_FALLBACK_ADAPTER"] = str(route.get("fallback_provider_adapter", ""))
                env["FDE_PROMPT_PACK_ID"] = str(route.get("prompt_pack_id", ""))
                env["FDE_PROMPT_PACK_INSTRUCTIONS"] = str(route.get("prompt_pack_instructions", ""))
                env["FDE_PROVIDER_ADAPTER"] = str(route.get("provider_adapter", ""))
                env["FDE_MEDIA_PROVIDER"] = str(route.get("provider", ""))
                env["FDE_MEDIA_MODEL"] = str(route.get("model", ""))
                env["FDE_MEDIA_TIMEOUT"] = str(route.get("timeout_seconds", 3600))
                env["FDE_MEDIA_COMMAND"] = str(route.get("media_command_template", ""))
                env["FDE_MEDIA_QUALITY"] = str(route.get("quality", ""))
                env["FDE_MEDIA_RESOLUTION"] = str(route.get("resolution", ""))
                env["FDE_MEDIA_ASPECT_RATIO"] = str(route.get("aspect_ratio", "16:9"))
                env["FDE_MEDIA_DURATION"] = str(route.get("duration_seconds", 0) or "")
                env["FDE_VOICE_MODEL"] = str(route.get("model", ""))
                env["FDE_VOICE_NAME"] = str(route.get("voice", ""))
                if task_id == "word_alignment":
                    env["FDE_WHISPER_MODEL"] = str(route.get("model", "base.en"))
            elif config.get("command_template"):
                env["FDE_LLM_COMMAND"] = str(config["command_template"])
            log_path = self.log_path(project_id)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = log_path.open("a", encoding="utf-8")
            if restart_report:
                log_handle.write(f"\n[{utc_now()}] RESTART {restart_report['stage_id']} archived to {restart_report['history_path']}\n")
            log_handle.write(f"\n[{utc_now()}] START {action}\n$ {' '.join(command)}\n\n")
            log_handle.flush()
            process = subprocess.Popen(
                command, cwd=Path(__file__).resolve().parents[2], stdout=log_handle,
                stderr=subprocess.STDOUT, text=True, env=env, start_new_session=True,
            )
            self._processes[project_id] = process
            state = {
                "status": "running", "action": action, "label": action.replace("_", " ").title(),
                "started_at": utc_now(), "ended_at": None, "return_code": None, "error": None,
                "pid": process.pid, "restart": restart_report,
                "routing": ({
                    "task_id": task_id, "provider": route.get("provider"),
                    "provider_label": route.get("provider_label"), "model": route.get("model"),
                    "reasoning_effort": route.get("reasoning_effort"), "quality": route.get("quality"),
                    "resolution": route.get("resolution"), "aspect_ratio": route.get("aspect_ratio"),
                    "duration_seconds": route.get("duration_seconds"), "voice": route.get("voice"),
                    "fallback_provider": route.get("fallback_provider"), "fallback_model": route.get("fallback_model"),
                    "capability": route.get("capability"), "adapter": route.get("provider_adapter"),
                    "matched_rule": route.get("matched_rule"),
                } if route else None),
            }
            write_json(self.state_path(project_id), state)
            threading.Thread(target=self._wait_for_job, args=(project_id, process, log_handle, state), daemon=True).start()
            return state

    def stop(self, project_id: str) -> dict[str, Any]:
        with self._lock:
            process = self._processes.get(project_id)
            if not process or process.poll() is not None:
                state = self.state(project_id)
                if state["status"] == "running":
                    state["status"] = "interrupted"
                    state["ended_at"] = utc_now()
                    write_json(self.state_path(project_id), state)
                return state
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except Exception:
                process.terminate()
            return {**self.state(project_id), "status": "stopping"}

    def _wait_for_job(self, project_id: str, process: subprocess.Popen[str], log_handle, state: dict[str, Any]) -> None:
        return_code = process.wait()
        log_handle.write(f"\n[{utc_now()}] END return_code={return_code}\n")
        log_handle.close()
        status = "completed" if return_code == 0 else "waiting" if return_code == 2 else "failed"
        state.update({
            "status": status, "ended_at": utc_now(), "return_code": return_code,
            "error": None if return_code in {0, 2} else f"Command exited with status {return_code}",
        })
        write_json(self.state_path(project_id), state)
        with self._lock:
            self._processes.pop(project_id, None)

    def _reconcile_stale_jobs(self) -> None:
        if not self.workspace.exists():
            return
        for path in self.workspace.glob("*/studio_run.json"):
            try:
                state = read_json(path)
            except Exception:
                continue
            if state.get("status") == "running":
                state["status"] = "interrupted"
                state["ended_at"] = utc_now()
                state["error"] = "Studio restarted while this job was running"
                write_json(path, state)
