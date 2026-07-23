from __future__ import annotations

"""Patch the existing resumable JobManager with two-pass production actions."""

from . import jobs as _base

_base.ACTION_COMMANDS.update(
    {
        "shot_skeleton": ["shot-skeleton", "{project}"],
        "master_footage": ["master-footage", "{project}", "--agent", "{agent}"],
        "consume_master_footage": [
            "master-footage", "{project}", "--agent", "manual", "--consume-response"
        ],
        "editorial_shots": ["editorial-shots", "{project}", "--agent", "{agent}"],
        "consume_editorial_shots": [
            "editorial-shots", "{project}", "--agent", "manual", "--consume-response"
        ],
    }
)
# The old `shots` action remains a compatibility alias for the deterministic skeleton.
_base.ACTION_COMMANDS["shots"] = ["shot-skeleton", "{project}"]

_base.ACTION_TASKS.update(
    {
        "shot_skeleton": "word_alignment",
        "shots": "word_alignment",
        "master_footage": "master_footage_planner",
        "editorial_shots": "editorial_director",
        "prepare_images": "image_generator",
        "prepare_videos": "video_generator",
    }
)

ACTION_COMMANDS = _base.ACTION_COMMANDS
ACTION_TASKS = _base.ACTION_TASKS
JobManager = _base.JobManager
