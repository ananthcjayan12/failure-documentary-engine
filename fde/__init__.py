"""Failure Documentary Engine."""

__version__ = "0.6.0"

# Configure the two-pass routing graph before public modules are imported.
from . import orchestrator_two_pass as _orchestrator_two_pass  # noqa: F401,E402
