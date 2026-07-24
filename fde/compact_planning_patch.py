from __future__ import annotations

"""Activate compact planning and LLM-led editorial assignment safely."""

from . import compact_planning as _compact_planning
from . import editorial as _editorial
from . import master_footage as _master_footage
from . import shots as _shots
from .compact_planning import (
    install_agent_safety_patch,
    plan_semantic_shot_skeleton,
)
from .compact_planning_runtime import plan_master_footage_compact_runtime
from .llm_assignment_approval import approve_editorial_shots_llm_all
from .llm_editorial_assignment import direct_editorial_shots_llm_all


_shots.plan_shot_skeleton = plan_semantic_shot_skeleton
_shots.plan_shots = plan_semantic_shot_skeleton
_master_footage.plan_master_footage = plan_master_footage_compact_runtime
_compact_planning.direct_editorial_shots_compact = direct_editorial_shots_llm_all
_editorial.direct_editorial_shots = direct_editorial_shots_llm_all
_editorial.approve_editorial_shots = approve_editorial_shots_llm_all
install_agent_safety_patch()
