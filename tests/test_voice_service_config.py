from __future__ import annotations

from types import SimpleNamespace

from shuxin.voice.service import VoiceService
from shuxin.voice.config.config import DeviceConfig, LLMDeviceConfig


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


def test_voice_service_isolates_deferred_memory_per_companion(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("SHUXIN_MEM0_ENABLED", "0")
    service = VoiceService(config_path=str(tmp_path / "missing-config.yaml"))
    device = DeviceConfig(device_id="soft-device")
    user_home = tmp_path / "users" / "alice"

    agent_a = service.create_agent(
        device, user_home=user_home, companion_id="companion-a"
    )
    agent_b = service.create_agent(
        device, user_home=user_home, companion_id="companion-b"
    )

    assert agent_a.memory.data_dir == (
        user_home / "companions" / "companion-a" / "memory"
    )
    assert agent_b.memory.data_dir == (
        user_home / "companions" / "companion-b" / "memory"
    )
    assert agent_a.memory.mem0_user_id == "alice::companion::companion-a"
    assert agent_b.memory.mem0_user_id == "alice::companion::companion-b"
    assert agent_a.memory.defer_mem0_writes is True
    assert agent_b.memory.defer_mem0_writes is True
