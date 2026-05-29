from __future__ import annotations

from types import SimpleNamespace

from shuxin.voice.service import VoiceService
from shuxin.voice.config import DeviceConfig, LLMDeviceConfig


def test_voice_service_build_config_caps_history_and_tokens(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_VOICE_MAX_HISTORY", "6")
    monkeypatch.setenv("SHUXIN_VOICE_MAX_TOKENS", "256")

    service = VoiceService(config_path=str(tmp_path / "missing-config.yaml"))
    device = DeviceConfig(
        device_id="demo-device-001",
        llm=LLMDeviceConfig(
            provider="openai-compatible",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            api_key="test-key",
        ),
    )

    config = service.build_agent_config(device)

    assert config.max_history == 6
    assert config.llm.max_tokens == 256
    assert config.llm.model == "deepseek-v4-flash"
