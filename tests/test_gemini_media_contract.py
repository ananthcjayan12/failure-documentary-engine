from fde.providers.gemini_api import (
    _normalize_image_size,
    _normalize_video_resolution,
    _provider_video_duration,
)


def test_gemini_image_sizes_use_current_api_values():
    assert _normalize_image_size("0.5K") == "512"
    assert _normalize_image_size("1k") == "1K"
    assert _normalize_image_size("2k") == "2K"
    assert _normalize_image_size("4k") == "4K"


def test_veo_uses_lowercase_4k_and_requires_eight_seconds_for_high_resolution():
    assert _normalize_video_resolution("4K") == "4k"
    assert _normalize_video_resolution("1080P") == "1080p"
    assert _provider_video_duration("veo-3.1-generate-preview", "1080p", 4) == 8
    assert _provider_video_duration("veo-3.1-fast-generate-preview", "4k", 6) == 8
    assert _provider_video_duration("veo-3.1-generate-preview", "720p", 6) == 6


def test_gemini_omni_duration_stays_between_three_and_ten_seconds():
    assert _provider_video_duration("gemini-omni-flash-preview", "720p", 1) == 3
    assert _provider_video_duration("gemini-omni-flash-preview", "720p", 12) == 10
