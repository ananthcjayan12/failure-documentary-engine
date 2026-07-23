from fde.orchestrator import merge_orchestrator_config, resolve_task


def test_pre_v1_saved_routes_do_not_corrupt_audio_first_router():
    legacy = {
        "version": 2,
        "active_profile": "highest_quality",
        "active_prompt_pack": "engineering_failure",
        "tasks": {
            "structure": {
                "provider": "claude_code",
                "model": "claude-opus-4-8",
                "fallback_provider": "codex",
                "fallback_model": "gpt-5.6-sol",
            },
            "image_generator": {
                "provider": "grok_cli",
                "model": "authenticated-default",
                "fallback_provider": "chatgpt_ui",
                "fallback_model": "ChatGPT Images",
            },
            "video_generator": {
                "provider": "grok_cli",
                "model": "authenticated-default",
                "fallback_provider": "grok_ui",
                "fallback_model": "Grok Imagine",
            },
        },
        "providers": {
            "codex": {"command_template": "custom-codex {prompt} {output}", "enabled": True},
            "claude_code": {"command_template": "legacy", "enabled": True},
        },
    }

    migrated = merge_orchestrator_config(legacy)

    assert migrated["version"] == 4
    assert migrated["active_profile"] == "highest_quality"
    assert migrated["active_prompt_pack"] == "engineering_failure"
    assert migrated["tasks"]["structure"]["provider"] == "anthropic_api"
    assert migrated["tasks"]["image_generator"]["model"] == "grok-imagine-image-quality"
    assert migrated["tasks"]["video_generator"]["model"] == "grok-imagine-video-1.5"
    assert migrated["providers"]["codex"]["command_template"] == "custom-codex {prompt} {output}"
    assert "claude_code" not in migrated["providers"]
    resolve_task(migrated, "structure")
    resolve_task(migrated, "image_generator")
    resolve_task(migrated, "video_generator")


def test_invalid_v1_custom_route_falls_back_to_task_default():
    saved = {
        "version": 4,
        "active_profile": "custom",
        "tasks": {
            "image_generator": {
                "provider": "grok_cli",
                "model": "authenticated-default",
                "resolution": "2K",
                "fallback_provider": "chatgpt_ui",
                "fallback_model": "ChatGPT Images",
            }
        },
    }

    migrated = merge_orchestrator_config(saved)

    assert migrated["active_profile"] == "custom"
    assert migrated["tasks"]["image_generator"]["model"] == "grok-imagine-image-quality"
    resolve_task(migrated, "image_generator")
