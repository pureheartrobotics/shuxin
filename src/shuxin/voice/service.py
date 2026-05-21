from __future__ import annotations

from pathlib import Path

from shuxin.core.agent import Agent
from shuxin.core.config import Config
from shuxin.voice.config import DeviceConfig, DeviceConfigProvider
from shuxin.voice.providers import create_stt_provider, create_tts_provider


class VoiceService:
    def __init__(
        self,
        device_provider: DeviceConfigProvider | None = None,
        config_path: str | None = None,
    ) -> None:
        self.device_provider = device_provider or DeviceConfigProvider()
        self.config_path = config_path

    async def transcribe(self, audio_path: Path, device_id: str | None = None) -> str:
        device = self.device_provider.get(device_id)
        provider = create_stt_provider(device.stt)
        return await provider.transcribe(audio_path)

    async def synthesize(
        self,
        text: str,
        output_path: Path,
        device_id: str | None = None,
    ) -> Path:
        device = self.device_provider.get(device_id)
        provider = create_tts_provider(device.tts)
        return await provider.synthesize(text, output_path)

    async def chat_audio(
        self,
        audio_path: Path,
        output_path: Path,
        device_id: str | None = None,
    ) -> tuple[str, str, Path]:
        device = self.device_provider.get(device_id)
        text = await create_stt_provider(device.stt).transcribe(audio_path)
        reply = self.chat_text(text, device)
        speech_path = await create_tts_provider(device.tts).synthesize(reply, output_path)
        return text, reply, speech_path

    def chat_text(self, text: str, device: DeviceConfig) -> str:
        agent = self.create_agent(device)
        agent.initialize()
        try:
            return agent.chat(text).strip()
        finally:
            agent.shutdown()

    def create_agent(self, device: DeviceConfig) -> Agent:
        return Agent(config=self.build_agent_config(device))

    def build_agent_config(self, device: DeviceConfig) -> Config:
        return self._build_agent_config(device)

    def _build_agent_config(self, device: DeviceConfig) -> Config:
        config = Config.load(self.config_path)
        if device.llm.provider:
            config.llm.provider = device.llm.provider
        if device.llm.model:
            config.llm.model = device.llm.model
        if device.llm.base_url:
            config.llm.base_url = device.llm.base_url
        if device.llm.api_key:
            config.llm.api_key = device.llm.api_key
        return config
