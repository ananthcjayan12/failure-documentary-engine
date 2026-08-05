"""Provider-aware video duration planning.

Editorial and master-asset durations are contracts.  A provider may only offer
coarser generation buckets, so this module chooses a bucket that can cover the
contract and leaves local conforming to the media pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass


GROK_VIDEO_DURATIONS = (6.0, 10.0)


@dataclass(frozen=True)
class VideoDurationPlan:
    requested_duration_seconds: float
    provider_duration_seconds: float
    conform_duration_seconds: float


def compile_video_duration(
    provider: str,
    requested_duration_seconds: float,
) -> VideoDurationPlan:
    """Return a provider-valid duration without changing the edit contract."""
    requested = float(requested_duration_seconds)
    if requested <= 0:
        raise ValueError("requested video duration must be greater than zero")
    if provider != "grok_cli":
        return VideoDurationPlan(requested, requested, requested)

    for supported in GROK_VIDEO_DURATIONS:
        if requested <= supported:
            return VideoDurationPlan(requested, supported, requested)
    raise ValueError(
        f"Grok image_to_video supports at most {GROK_VIDEO_DURATIONS[-1]:g} seconds "
        f"per master asset; requested {requested:g}. Split the master package explicitly."
    )
