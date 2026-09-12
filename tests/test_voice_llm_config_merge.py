from __future__ import annotations

from shuxin.voice.config.config import LLMDeviceConfig, merge_llm_device_config


def test_empty_api_key_in_user_config_does_not_wipe_device_key() -> None:
    base = LLMDeviceConfig(
        provider="openai-compatible",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        api_key="device-key",
    )

    merged = merge_llm_device_config(base, {"model": "other-model", "api_key": ""})

    assert merged.model == "other-model"
    assert merged.api_key == "device-key"
    assert merged.base_url == "https://api.deepseek.com"


def test_nonempty_override_wins() -> None:
    base = LLMDeviceConfig(
        provider="openai-compatible",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        api_key="device-key",
    )

    merged = merge_llm_device_config(
        base,
        {"api_key": "user-key", "base_url": "https://example.com/v1"},
    )

    assert merged.api_key == "user-key"
    assert merged.base_url == "https://example.com/v1"
