"""Tests for Agent model, TTS resolution, and repository helpers."""

from __future__ import annotations

import pytest

from shuxin.voice.agents import AgentRecord, invalidate_agent_cache
from shuxin.voice.tts_config import resolve_tts_config_from_agent


def test_resolve_tts_config_from_agent(monkeypatch) -> None:
    monkeypatch.setenv("VOLCENGINE_TTS_API_KEY", "test-key")
    monkeypatch.delenv("VOLCENGINE_TTS_VOICE_TYPE", raising=False)
    agent = AgentRecord(
        agent_id="shuxin",
        voice_type="voice_shuxin_001",
        cluster="volcano_icl",
        speed_ratio=0.95,
        uid="shuxin",
    )
    resolved = resolve_tts_config_from_agent(agent)
    assert resolved.voice_type == "voice_shuxin_001"
    assert resolved.api_key == "test-key"
    assert resolved.speed_ratio == pytest.approx(0.95)
    assert resolved.profile_id == "shuxin"


def test_resolve_tts_config_from_agent_env_fallback(monkeypatch) -> None:
    monkeypatch.setenv("VOLCENGINE_TTS_API_KEY", "test-key")
    monkeypatch.setenv("VOLCENGINE_TTS_VOICE_TYPE", "env_voice")
    agent = AgentRecord(agent_id="shuxin", voice_type="")
    resolved = resolve_tts_config_from_agent(agent)
    assert resolved.voice_type == "env_voice"


def test_agent_record_admin_dict_unmasked() -> None:
    record = AgentRecord(agent_id="a1", voice_type="S_full_voice_id")
    public = record.to_public_dict()
    admin = record.to_admin_dict()
    assert public["voice_type"] != "S_full_voice_id"
    assert admin["voice_type"] == "S_full_voice_id"


def test_invalidate_agent_cache() -> None:
    from shuxin.voice.agents import cache_agent, get_cached_agent

    record = AgentRecord(agent_id="cache-test", voice_type="v")
    cache_agent(record)
    assert get_cached_agent("cache-test") is not None
    invalidate_agent_cache("cache-test")
    assert get_cached_agent("cache-test") is None


def test_voice_service_applies_device_mbti() -> None:
    from shuxin.core.agent import Agent
    from shuxin.core.config import Config
    from shuxin.voice.config import DeviceConfig
    from shuxin.voice.service import VoiceService

    service = VoiceService()
    device = DeviceConfig(device_id="d1", metadata={"mbti": "ENFP"})
    agent_record = AgentRecord(agent_id="shuxin", metadata={"default_mbti": "INFJ"})
    config = service.build_agent_config(device, agent=agent_record)
    agent = Agent(config=config)
    agent.soul.profile.mbti = "INFJ"
    agent.identity.set_mbti("INFJ")
    agent._initialized = True
    VoiceService.apply_device_mbti(agent, device, agent_record)
    assert agent.identity.profile.mbti == "ENFP"
