from __future__ import annotations

import asyncio
import re
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from shuxin.voice.audio_effects import is_karen_style_effect
from shuxin.voice.config import ProviderConfig, resolve_tts_effect

if TYPE_CHECKING:
    from shuxin.voice.tts_config import ResolvedTtsConfig


class STTProvider(ABC):
    """语音识别 provider 抽象。"""

    @abstractmethod
    async def transcribe(self, audio_path: Path) -> str:
        """把音频文件识别为文本。"""


class TTSProvider(ABC):
    """语音合成 provider 抽象。"""

    @abstractmethod
    async def synthesize(self, text: str, output_path: Path) -> Path:
        """把文本合成为音频文件，并返回输出路径。"""


class APIProviderNotImplemented(RuntimeError):
    pass


class FakeSTTProvider(STTProvider):
    """测试用 STT provider，不依赖模型和网络。"""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    async def transcribe(self, audio_path: Path) -> str:
        """直接返回配置里的 model 字段，方便测试断言。"""
        return self.config.model or "测试语音"


class FakeTTSProvider(TTSProvider):
    """测试用 TTS provider，生成带固定头的假 mp3 payload。"""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    async def synthesize(self, text: str, output_path: Path) -> Path:
        """把文本写成可识别的字节内容，不调用真实 TTS 服务。"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"FAKE_MP3:" + text.encode("utf-8"))
        return output_path


class APISTTProvider(STTProvider):
    """预留的远程 STT provider，占位远程服务接入点。"""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    async def transcribe(self, audio_path: Path) -> str:
        raise APIProviderNotImplemented(
            "API STT provider is reserved for future use in this demo."
        )


class APITTSProvider(TTSProvider):
    """预留的远程 TTS provider，占位远程服务接入点。"""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    async def synthesize(self, text: str, output_path: Path) -> Path:
        raise APIProviderNotImplemented(
            "API TTS provider is reserved for future use in this demo."
        )


class FunASRLocalProvider(STTProvider):
    """本地 FunASR 文件识别 provider。"""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        self.model_dir = Path(config.model_dir)
        self._model = None

    def _load_model(self):
        """懒加载 FunASR 模型，避免 CLI help 等轻量命令提前初始化。"""
        if self._model is not None:
            return self._model
        try:
            from funasr import AutoModel
        except ImportError as exc:
            raise RuntimeError(
                "FunASR is not installed. Install requirements-voice-stack.txt "
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
        """在线程池中运行阻塞的 FunASR generate 调用。"""
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


class FunASRStreamingLocalProvider(FunASRLocalProvider):
    """FunASR streaming 模型适配器。

    第一版 Web demo 仍然在 listen stop 后返回最终识别文本。这里先通过
    同一个文件识别接口加载 streaming 模型，便于先验证浏览器/硬件传输链路；
    后续再把中间识别结果提升为公开协议。
    """


class EdgeTTSProvider(TTSProvider):
    """EdgeTTS 本地封装 provider。"""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        self.voice = config.voice or "zh-CN-XiaoyiNeural"
        self.rate = config.rate or "-8%"
        self.pitch = config.pitch or "-2Hz"
        self.volume = config.volume or "+0%"
        self._effect, self._effect_strength = resolve_tts_effect(config)

    def _communicate_kwargs(self) -> dict[str, str]:
        return {
            "rate": self.rate,
            "pitch": self.pitch,
            "volume": self.volume,
        }

    async def synthesize(self, text: str, output_path: Path) -> Path:
        """调用 edge-tts 生成 mp3；如果目标是 wav，则再转码一次。"""
        if not text.strip():
            raise ValueError("TTS text cannot be empty.")

        try:
            import edge_tts
        except ImportError as exc:
            raise RuntimeError(
                "edge-tts is not installed. Install requirements-voice-stack.txt "
                "or build the Docker image."
            ) from exc

        output_path = output_path.expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        communicate = edge_tts.Communicate(
            text,
            self.voice,
            **self._communicate_kwargs(),
        )

        if output_path.suffix.lower() == ".wav":
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as tmp:
                await communicate.save(tmp.name)
                await asyncio.to_thread(
                    _finalize_tts_file,
                    Path(tmp.name),
                    output_path,
                    self._effect,
                    self._effect_strength,
                )
        else:
            await communicate.save(str(output_path))
            if is_karen_style_effect(self._effect):
                await asyncio.to_thread(
                    _apply_karen_to_file,
                    output_path,
                    self._effect_strength,
                )
        return output_path


def create_stt_provider(config: ProviderConfig) -> STTProvider:
    """根据设备配置创建 STT provider。"""
    provider_type = (config.type or "local").lower()
    if provider_type == "local":
        return FunASRLocalProvider(config)
    if provider_type in {"streaming-local", "local-streaming"}:
        return FunASRStreamingLocalProvider(config)
    if provider_type == "api":
        return APISTTProvider(config)
    if provider_type == "fake":
        return FakeSTTProvider(config)
    raise ValueError(f"Unsupported STT provider type: {config.type}")


def create_tts_provider(
    config: ProviderConfig,
    *,
    resolved: "ResolvedTtsConfig | None" = None,
) -> TTSProvider:
    """根据设备配置创建 TTS provider。"""
    from shuxin.voice.tts_config import ResolvedTtsConfig, resolve_tts_config

    provider_type = (config.type or "volcengine-clone").lower()
    if provider_type in {"volcengine-clone", "volcengine", "volc-clone"}:
        from shuxin.voice.volcengine_tts import VolcengineCloneTTSProvider

        cfg: ResolvedTtsConfig = resolved or resolve_tts_config(config)
        return VolcengineCloneTTSProvider(cfg)
    if provider_type == "local":
        import logging

        logging.getLogger(__name__).warning(
            "TTS type=local (EdgeTTS) is deprecated for production; use volcengine-clone"
        )
        return EdgeTTSProvider(config)
    if provider_type == "api":
        from shuxin.voice.tts_config import resolve_tts_config as _resolve
        from shuxin.voice.volcengine_tts import VolcengineCloneTTSProvider

        cfg = resolved or _resolve(config)
        if cfg.provider_type in {"volcengine-clone", "volcengine", "volc-clone"}:
            return VolcengineCloneTTSProvider(cfg)
        raise APIProviderNotImplemented(
            "API TTS provider is reserved for future use in this demo."
        )
    if provider_type == "fake":
        return FakeTTSProvider(config)
    raise ValueError(f"Unsupported TTS provider type: {config.type}")


def _extract_funasr_text(result) -> str:
    """从 FunASR 返回结构中提取纯文本，并清理 SenseVoice 标签。"""
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


def _apply_karen_to_file(path: Path, strength: str) -> None:
    from pydub import AudioSegment

    from shuxin.voice.audio_effects import apply_karen_voice

    fmt = path.suffix.lower().lstrip(".") or "mp3"
    audio = AudioSegment.from_file(str(path))
    audio = apply_karen_voice(audio, strength=strength)
    audio.export(str(path), format=fmt)


def _finalize_tts_file(
    input_path: Path,
    output_path: Path,
    effect: str,
    effect_strength: str,
) -> None:
    """Convert mp3 to wav and optionally apply electric post-processing."""
    try:
        from pydub import AudioSegment
    except ImportError as exc:
        raise RuntimeError(
            "pydub is required when the output path ends with .wav."
        ) from exc
    audio = AudioSegment.from_file(str(input_path))
    if is_karen_style_effect(effect):
        from shuxin.voice.audio_effects import apply_karen_voice

        audio = apply_karen_voice(audio, strength=effect_strength)
    audio.export(str(output_path), format="wav")


def _convert_to_wav(input_path: Path, output_path: Path) -> None:
    """使用 pydub 把临时 mp3 转为 wav。"""
    _finalize_tts_file(input_path, output_path, "none", "medium")
