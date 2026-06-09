from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from shuxin.voice.agents import AgentRecord
from shuxin.voice.config import DeviceConfig, LLMDeviceConfig, ProviderConfig
from shuxin.voice.server import _VoiceWebSocketSession
from shuxin.voice.users import UserSettings


def _make_session() -> _VoiceWebSocketSession:
    ws = SimpleNamespace(send_text=AsyncMock())
    return _VoiceWebSocketSession(
        websocket=ws,
        service=MagicMock(),
        repo=SimpleNamespace(),
        shuxin_home=Path("/tmp/shuxin-test"),
        default_device_id="SX-000113",
        out_dir=Path("/tmp/shuxin-out"),
    )


def test_ensure_runtime_inits_agent_when_device_prefetched() -> None:
    """MBTI intro loads device before _ensure_runtime; agent must still be created."""
    session = _make_session()
    session.device_id = "SX-000113"
    session.user_id = "wx_test_user"
    session.user_settings = UserSettings(
        user_id="wx_test_user",
        token="",
        audio_quota_mb=512,
        llm_config={"api_key": "test-key", "model": "deepseek-chat", "base_url": "https://api.example.com"},
        agent_id="shuxin",
    )
    session.audio_store = MagicMock()
    session.audio_store.user_shuxin_home.return_value = Path("/tmp/shuxin-test/users/wx_test_user")
    session.device = DeviceConfig(
        device_id="SX-000113",
        llm=LLMDeviceConfig(api_key="device-key", model="m1", base_url="https://device.example.com"),
        stt=ProviderConfig(type="tencent-realtime"),
        metadata={"mbti": "ENFJ", "mbti_status": "locked", "device_intro_played": False},
    )
    session.agent = None
    session.tts = None
    session.stt = None

    mock_agent = MagicMock()
    mock_agent.context = SimpleNamespace(metadata={})
    mock_agent.initialize = MagicMock()
    session.service.create_agent.return_value = mock_agent
    session.repo.get_agent = AsyncMock(
        return_value=AgentRecord(agent_id="shuxin", display_name="舒心", voice_type="S_test")
    )
    session.repo.get_user_agent_id = AsyncMock(return_value="shuxin")

    fake_tts = MagicMock()

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args)

    with patch("shuxin.voice.server.create_tts_provider_from_agent", return_value=fake_tts):
        with patch("shuxin.voice.server.VoiceService.apply_device_mbti"):
            with patch("shuxin.voice.server.asyncio.to_thread", new=fake_to_thread, create=True):
                asyncio.run(session._ensure_runtime())

    assert session.agent is mock_agent
    assert session.tts is fake_tts
    session.service.create_agent.assert_called_once()
    mock_agent.initialize.assert_called_once()


def test_play_pending_device_intro_leaves_agent_ready_for_chat() -> None:
    """After intro path, agent exists so chat_stream would not hit None."""
    session = _make_session()
    session.device_id = "SX-000113"
    session.user_id = "wx_test_user"
    session.user_settings = UserSettings(
        user_id="wx_test_user",
        token="",
        audio_quota_mb=512,
        llm_config={"api_key": "test-key", "model": "deepseek-chat"},
        agent_id="shuxin",
    )
    session.audio_store = MagicMock()
    session.audio_store.user_shuxin_home.return_value = Path("/tmp/shuxin-test/users/wx_test_user")

    device = DeviceConfig(
        device_id="SX-000113",
        llm=LLMDeviceConfig(api_key="test-key", model="m1", base_url="https://api.example.com"),
        stt=ProviderConfig(type="tencent-realtime"),
        metadata={"mbti": "ENFJ", "mbti_status": "locked", "device_intro_played": False},
    )
    session.repo.get_device = AsyncMock(return_value=device)
    session.repo.mark_device_intro_played = AsyncMock(return_value={"device_intro_played": True})
    session.repo.get_agent = AsyncMock(return_value=AgentRecord(agent_id="shuxin"))

    mock_agent = MagicMock()
    mock_agent.context = SimpleNamespace(metadata={})
    mock_agent.initialize = MagicMock()
    mock_agent.chat_stream = MagicMock(return_value=iter(["你好"]))
    session.service.create_agent.return_value = mock_agent

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args)

    async def run() -> None:
        with patch("shuxin.voice.server.create_tts_provider_from_agent", return_value=MagicMock()):
            with patch("shuxin.voice.server.VoiceService.apply_device_mbti"):
                with patch("shuxin.voice.server.asyncio.to_thread", new=fake_to_thread, create=True):
                    with patch.object(session, "_play_proactive_tts", new_callable=AsyncMock):
                        played = await session.play_pending_device_intro(bind_success_prefix=True)
        assert played is True
        assert session.agent is mock_agent
        chunks = list(mock_agent.chat_stream("测试"))
        assert chunks == ["你好"]

    asyncio.run(run())
