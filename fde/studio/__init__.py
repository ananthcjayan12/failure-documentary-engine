"""Modern local control room for the Failure Documentary Engine."""

from . import jobs_two_pass as _jobs_two_pass  # noqa: F401
from .server import create_app

__all__ = ["create_app"]
