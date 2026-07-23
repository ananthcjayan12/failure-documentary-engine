from __future__ import annotations

"""Activate the compact planning implementation without breaking legacy imports."""

from . import editorial as _editorial
from . import master_footage as _master_footage
from . import shots as _shots
from .compact_planning import (
    direct_editorial_shots_compact,
    install_agent_safety_patch,
    plan_master_footage_compact,
    plan_semantic_shot_skeleton,
)


_shots.plan_shot_skeleton = plan_semantic_shot_skeleton
_shots.plan_shots = plan_semantic_shot_skeleton
_master_footage.plan_master_footage = plan_master_footage_compact
_editorial.direct_editorial_shots = direct_editorial_shots_compact
install_agent_safety_patch()
