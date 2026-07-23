from __future__ import annotations

from typing import Any

from ..io import write_json
from .service_two_pass import TwoPassStudioService


def save_manual_response(
    self: TwoPassStudioService,
    project_id: str,
    stage: str,
    value: Any,
):
    aliases = {
        "research": "research",
        "structure": "structure",
        "narration": "script",
        "script": "script",
        "master_footage": "master_footage",
        "editorial_shots": "editorial_shots",
    }
    if stage not in aliases:
        raise ValueError(
            "manual response stage must be research, structure, narration, "
            "master_footage, or editorial_shots"
        )
    request_dir = self.store.project_dir(project_id) / "_requests"
    prompt_stage = aliases[stage]
    if not (request_dir / f"{prompt_stage}_prompt.md").exists():
        raise FileNotFoundError(f"no pending manual request for {stage}")
    path = request_dir / f"{prompt_stage}_response.json"
    write_json(path, value)
    return path


TwoPassStudioService.save_manual_response = save_manual_response
