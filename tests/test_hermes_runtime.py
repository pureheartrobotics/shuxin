from __future__ import annotations

from shuxin.core.config import Config
from shuxin.integrations.hermes.runtime import (
    DANGEROUS_TOOLSETS,
    HermesVoiceAgent,
    create_voice_agent,
)


class FakeHermes:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.ephemeral_system_prompt = kwargs.get("ephemeral_system_prompt")

    def run_conversation(
        self,
        user_message,
        conversation_history=None,
        system_message=None,
        stream_callback=None,
    ):
        history = list(conversation_history or [])
        history.append({"role": "user", "content": user_message})
        reply = "在呢，我是初心。"
        if callable(stream_callback):
            stream_callback("在呢，")
            stream_callback("我是初心。")
        history.append({"role": "assistant", "content": reply})
        return {"final_response": reply, "messages": history}


def test_create_voice_agent_defaults_to_hermes(monkeypatch):
    monkeypatch.delenv("SHUXIN_AGENT_RUNTIME", raising=False)
    agent = create_voice_agent(Config())
    assert isinstance(agent, HermesVoiceAgent)


def test_legacy_runtime_opt_in(monkeypatch):
    monkeypatch.setenv("SHUXIN_AGENT_RUNTIME", "chuxin")
    from shuxin.core.agent import Agent

    agent = create_voice_agent(Config())
    assert isinstance(agent, Agent)


def test_hermes_chat_and_disabled_toolsets(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "shuxin.integrations.hermes.runtime.load_ai_agent_class",
        lambda: FakeHermes,
    )
    config = Config()
    config.llm.api_key = "test-key"
    config.llm.model = "deepseek-chat"
    config.shuxin_home = str(tmp_path)
    agent = HermesVoiceAgent(config)
    agent.initialize()
    for name in DANGEROUS_TOOLSETS:
        assert name in agent._hermes.kwargs["disabled_toolsets"]
    assert agent._hermes.kwargs["quiet_mode"] is True
    assert agent._hermes.kwargs.get("platform") == "voice"
    assert agent._hermes.kwargs.get("load_soul_identity") is False
    assert agent.llm.api_key == "test-key"
    assert agent.chat("你好") == "在呢，我是初心。"
    chunks = list(agent.chat_stream("还在吗"))
    assert chunks == ["在呢，", "我是初心。"]
    agent.shutdown()
    assert agent._hermes is None


def test_voice_service_create_agent_defaults_to_hermes(monkeypatch, tmp_path):
    monkeypatch.delenv("SHUXIN_AGENT_RUNTIME", raising=False)
    from shuxin.voice.config.config import DeviceConfig
    from shuxin.voice.service import VoiceService

    service = VoiceService(config_path=str(tmp_path / "missing-config.yaml"))
    agent = service.create_agent(DeviceConfig(device_id="demo-device-001"))
    assert isinstance(agent, HermesVoiceAgent)
