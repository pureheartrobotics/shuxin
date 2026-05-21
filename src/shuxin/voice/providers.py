from __future__ import annotations

import asyncio
import re
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

from shuxin.voice.config import ProviderConfig


class STTProvider(ABC):
    @abstractmethod
    async def transcribe(self, audio_path: Path) -> str:
        """Convert an audio file into text."""


class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str, output_path: Path) -> Path:
        """Convert text into an audio file."""


class APIProviderNotImplemented(RuntimeError):
    pass


class APISTTProvider(STTProvider):
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    async def transcribe(self, audio_path: Path) -> str:
        raise APIProviderNotImplemented(
            "API STT provider is reserved for future use in this demo."
        )


class APITTSProvider(TTSProvider):
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    async def synthesize(self, text: str, output_path: Path) -> Path:
        raise APIProviderNotImplemented(
            "API TTS provider is reserved for future use in this demo."
        )


class FunASRLocalProvider(STTProvider):
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        self.model_dir = Path(config.model_dir)
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return self._model
        try:
            from funasr import AutoModel
        except ImportError as exc:
            raise RuntimeError(
                "FunASR is not installed. Install requirements-voice-demo.txt "
                "or build the Docker image."
            ) from exc

        if not self.model_dir.exists():
            raise FileNotFoundError(
                f"FunASR model directory not found: {self.model_dir}"
            )

        self._model = AutoModel(
            model=str(self.model_dir),
            vad_kwargs={"max_single_segment_time": 30000},
            disable_update=True,
            hub="hf",
        )
        return self._model

    async def transcribe(self, audio_path: Path) -> str:
        audio_path = audio_path.expanduser()
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        model = self._load_model()
        result = await asyncio.to_thread(
            model.generate,
            input=str(audio_path),
            cache={},
            language="auto",
            use_itn=True,
            batch_size_s=60,
        )
        return _extract_funasr_text(result)


class EdgeTTSProvider(TTSProvider):
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        self.voice = config.voice or "zh-CN-XiaoxiaoNeural"

    async def synthesize(self, text: str, output_path: Path) -> Path:
        if not text.strip():
            raise ValueError("TTS text cannot be empty.")

        try:
            import edge_tts
        except ImportError as exc:
            raise RuntimeError(
                "edge-tts is not installed. Install requirements-voice-demo.txt "
                "or build the Docker image."
            ) from exc

        output_path = output_path.expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if output_path.suffix.lower() == ".wav":
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as tmp:
                await edge_tts.Communicate(text, self.voice).save(tmp.name)
                await asyncio.to_thread(_convert_to_wav, Path(tmp.name), output_path)
        else:
            await edge_tts.Communicate(text, self.voice).save(str(output_path))
        return output_path


def create_stt_provider(config: ProviderConfig) -> STTProvider:
    provider_type = (config.type or "local").lower()
    if provider_type == "local":
        return FunASRLocalProvider(config)
    if provider_type == "api":
        return APISTTProvider(config)
    raise ValueError(f"Unsupported STT provider type: {config.type}")


def create_tts_provider(config: ProviderConfig) -> TTSProvider:
    provider_type = (config.type or "local").lower()
    if provider_type == "local":
        return EdgeTTSProvider(config)
    if provider_type == "api":
        return APITTSProvider(config)
    raise ValueError(f"Unsupported TTS provider type: {config.type}")


def _extract_funasr_text(result) -> str:
    if isinstance(result, list) and result:
        item = result[0]
    else:
        item = result

    if isinstance(item, dict):
        text = item.get("text") or item.get("content") or ""
    else:
        text = str(item or "")

    # SenseVoice-style tags look like <|zh|><|NEUTRAL|><|Speech|>.
    text = re.sub(r"<\|[^|]+?\|>", "", text)
    return text.strip()


def _convert_to_wav(input_path: Path, output_path: Path) -> None:
    try:
        from pydub import AudioSegment
    except ImportError as exc:
        raise RuntimeError(
            "pydub is required when the output path ends with .wav."
        ) from exc
    audio = AudioSegment.from_file(str(input_path))
    audio.export(str(output_path), format="wav")
