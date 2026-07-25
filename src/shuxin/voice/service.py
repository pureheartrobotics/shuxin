from __future__ import annotations

import os
from pathlib import Path

from shuxin.core.agent import Agent
from shuxin.core.config import Config
from shuxin.core.identity import VALID_MBTI_TYPES
from shuxin.voice.persistence.agents import AgentRecord
from shuxin.voice.config.config import DeviceConfig, DeviceConfigProvider
from shuxin.voice.providers import create_stt_provider
from shuxin.voice.config.tts_config import create_tts_provider_from_agent, create_tts_provider_from_device


def _voice_max_history() -> int:
    return int(os.environ.get("SHUXIN_VOICE_MAX_HISTORY", "8"))


def _voice_max_tokens() -> int:
    return int(os.environ.get("SHUXIN_VOICE_MAX_TOKENS", "384"))


class VoiceService:
    """语音能力门面。

    CLI、WebSocket server 和无硬件 session 都通过这个类获取设备配置，
    再串起 STT、Agent 和 TTS。它不持有长会话状态，长会话由调用方管理。
    """

    def __init__(
        self,
        device_provider: DeviceConfigProvider | None = None,
        config_path: str | None = None,
    ) -> None:
        self.device_provider = device_provider or DeviceConfigProvider()
        self.config_path = config_path

    async def transcribe(self, audio_path: Path, device_id: str | None = None) -> str:
        """按设备配置执行一次语音识别。"""
        device = self.device_provider.get(device_id)
        provider = create_stt_provider(device.stt)
        return await provider.transcribe(audio_path)

    async def synthesize(
        self,
        text: str,
        output_path: Path,
        device_id: str | None = None,
    ) -> Path:
        """按设备配置执行一次语音合成。"""
        device = self.device_provider.get(device_id)
        provider = create_tts_provider_from_device(device.tts)
        return await provider.synthesize(text, output_path)

    async def chat_audio(
        self,
        audio_path: Path,
        output_path: Path,
        device_id: str | None = None,
    ) -> tuple[str, str, Path]:
        """执行文件输入版完整语音闭环: STT -> Agent -> TTS。"""
        device = self.device_provider.get(device_id)
        text = await create_stt_provider(device.stt).transcribe(audio_path)
        reply = self.chat_text(text, device)
        speech_path = await create_tts_provider_from_device(device.tts).synthesize(reply, output_path)
        return text, reply, speech_path

    def chat_text(self, text: str, device: DeviceConfig, user_home: Path | None = None) -> str:
        """用指定设备的 LLM 配置执行一次文本对话。

        user_home 用于 Web 多用户路径，让同一用户复用自己的记忆和陪伴状态。
        """
        agent = self.create_agent(device, user_home=user_home)
        agent.initialize()
        try:
            return agent.chat(text).strip()
        finally:
            agent.shutdown()

    def create_agent(
        self,
        device: DeviceConfig,
        user_home: Path | None = None,
        *,
        agent: AgentRecord | None = None,
        companion_id: str | None = None,
    ) -> Agent:
        """根据设备和用户目录创建 Agent 实例。"""
        return Agent(
            config=self._build_agent_config(
                device,
                user_home=user_home,
                agent=agent,
                companion_id=companion_id,
            )
        )

    def build_agent_config(
        self,
        device: DeviceConfig,
        user_home: Path | None = None,
        *,
        agent: AgentRecord | None = None,
        companion_id: str | None = None,
    ) -> Config:
        """构建 Agent 配置，保留给测试直接断言配置合成结果。"""
        return self._build_agent_config(
            device,
            user_home=user_home,
            agent=agent,
            companion_id=companion_id,
        )

    def _build_agent_config(
        self,
        device: DeviceConfig,
        user_home: Path | None = None,
        *,
        agent: AgentRecord | None = None,
        companion_id: str | None = None,
    ) -> Config:
        """把设备级 LLM 配置覆盖到全局配置上。"""
        config = Config.load(self.config_path)
        if user_home is not None:
            # Web 多用户场景必须隔离 shuxin_home，否则长期记忆和陪伴状态会串用户。
            config.shuxin_home = str(user_home)
            cid = str(companion_id or "").strip()
            if cid:
                from shuxin.voice.engagement.relationship import ensure_companion_data_dir

                config.companion.data_dir = str(
                    ensure_companion_data_dir(Path(user_home), cid)
                )
            else:
                config.companion.data_dir = str(user_home / "companion")
        if agent is not None and agent.soul_path.strip():
            config.soul.soul_path = agent.soul_path.strip()
        if device.llm.provider:
            config.llm.provider = device.llm.provider
        if device.llm.model:
            config.llm.model = device.llm.model
        if device.llm.base_url:
            config.llm.base_url = device.llm.base_url
        if device.llm.api_key:
            config.llm.api_key = device.llm.api_key
        config.max_history = _voice_max_history()
        config.llm.max_tokens = _voice_max_tokens()
        return config

    @staticmethod
    def apply_device_mbti(agent: Agent, device: DeviceConfig, agent_record: AgentRecord | None) -> None:
        """Apply blind-box device MBTI after Agent.initialize()."""
        device_mbti = str(device.metadata.get("mbti") or "").strip().upper()
        if not device_mbti and agent_record is not None:
            device_mbti = str(agent_record.metadata.get("default_mbti") or "").strip().upper()
        if device_mbti and device_mbti in VALID_MBTI_TYPES:
            agent.identity.set_mbti(device_mbti)
            if agent._initialized:
                agent._build_system_prompt()
