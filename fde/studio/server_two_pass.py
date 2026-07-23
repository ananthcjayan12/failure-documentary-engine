from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import Body, HTTPException

from ..editorial import approve_editorial_shots
from ..master_footage import approve_master_footage
from ..models import ProjectState
from . import server as _base
from .restart import RESTART_SPECS, restart_stage

_ORIGINAL_CREATE_APP = _base.create_app

# Existing upload helpers use this expression. Accept new package IDs while
# preserving old SHOT_### and A## migration imports.
_base.SHOT_ID_RE = re.compile(r"(?:SHOT_\d{3}|[HLEA]\d{2,3})", re.I)


def _restart_request(action: str) -> tuple[str, bool] | None:
    for prefix, run_again in (("restart_", False), ("rerun_", True)):
        if action.startswith(prefix):
            stage_id = action[len(prefix):]
            if stage_id in RESTART_SPECS:
                return stage_id, run_again
    return None


def create_app(workspace: Path | str = "projects"):
    app = _ORIGINAL_CREATE_APP(workspace)
    service = app.state.service
    jobs = app.state.jobs

    app.router.routes = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == "/api/projects/{project_id}/actions/{action}"
            and "POST" in getattr(route, "methods", set())
        )
    ]

    @app.post("/api/projects/{project_id}/actions/{action}")
    def run_two_pass_action(
        project_id: str,
        action: str,
        payload: dict[str, Any] | None = Body(default=None),
    ) -> dict[str, Any]:
        _base._require_project(service, project_id)
        try:
            restart = _restart_request(action)
            if restart:
                stage_id, run_again = restart
                report = restart_stage(service.store, project_id, stage_id)
                if not run_again:
                    return {
                        "status": "completed",
                        "action": action,
                        "state": service.store.manifest(project_id).state.value,
                        "restart": report,
                    }
                return jobs.start(
                    project_id,
                    report["run_action"],
                    agent=(payload or {}).get("agent"),
                )
            if action == "approve_structure":
                service.store.approve_version(project_id, "structure")
                service.store.transition(project_id, ProjectState.STRUCTURE_APPROVED)
            elif action in {"approve_narration", "approve_script"}:
                service.store.approve_version(project_id, "narration")
                service.store.transition(project_id, ProjectState.NARRATION_APPROVED)
            elif action == "approve_voice":
                service.store.transition(project_id, ProjectState.VOICE_APPROVED)
            elif action == "approve_shot_skeleton":
                service.store.approve_version(project_id, "shot_skeleton")
                service.store.transition(project_id, ProjectState.SHOT_SKELETON_APPROVED)
            elif action == "approve_master_footage":
                approve_master_footage(service.store, project_id)
            elif action == "approve_shots":
                approve_editorial_shots(service.store, project_id)
            else:
                payload = payload or {}
                return jobs.start(project_id, action, agent=payload.get("agent"))
            return {
                "status": "completed",
                "action": action,
                "state": service.store.manifest(project_id).state.value,
            }
        except (ValueError, RuntimeError, FileNotFoundError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return app


# Code that imports fde.studio.server directly receives the corrected app factory.
_base.create_app = create_app
