"""Backward-compatible entry point for the modern Studio."""

from .studio.server import create_app

__all__ = ["create_app"]
