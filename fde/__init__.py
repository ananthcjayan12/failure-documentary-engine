"""Failure Documentary Engine."""

__version__ = "0.6.0"

# Package-wide compatibility and routing overlays must load before public modules.
from . import orchestrator_two_pass as _orchestrator_two_pass  # noqa: F401,E402
from . import visual_compat as _visual_compat  # noqa: F401,E402
