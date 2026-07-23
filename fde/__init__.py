"""Failure Documentary Engine."""

__version__ = "0.6.0"

# Importing the routing overlay mutates the provider task graph before Studio,
# CLI, or tests import the public orchestrator helpers.
from . import orchestrator_two_pass as _orchestrator_two_pass  # noqa: F401,E402
