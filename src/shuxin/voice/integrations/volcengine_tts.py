"""Volcengine OpenSpeech voice-clone TTS provider."""

from __future__ import annotations

import asyncio
import base64
import os
import uuid
from pathlib import Path
from typing import Any

import httpx

from shuxin.voice.providers import TTSProvider
from shuxin.voice.config.tts_config import ResolvedTtsConfig

VOLCENGINE_TTS_SUCCESS_CODE = 3000


class VolcengineTTSError(RuntimeError):
    """Raised when Volcengine TTS API returns an error."""

    def __init__(
        self,
        message: str,
        *,
        error_kind: str = "tts_error",
        status_code: int | None = None,
        api_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.error_kind = error_kind
        self.status_code = status_code
        self.api_code = api_code


def _tts_connect_timeout() -> float:
    raw = os.environ.get("SHUXIN_TTS_CONNECT_TIMEOUT_SECONDS", "5")
    try:
        return float(raw)
    except ValueError:
        return 5.0


def _tts_timeout() -> float:
    raw = os.environ.get("SHUXIN_TTS_TIMEOUT_SECONDS", "30")
    try:
        return float(raw)
    except ValueError:
        return 30.0


def _extract_audio_bytes(payload: dict[str, Any]) -> bytes:
    code = payload.get("code")
    if code is not None and int(code) != VOLCENGINE_TTS_SUCCESS_CODE:
        raise VolcengineTTSError(
            str(payload.get("message") or payload.get("msg") or "Volcengine TTS failed"),
            error_kind="tts_api_error",
            api_code=int(code),
        )

    for key in ("data", "audio", "audio_data"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return base64.b64decode(value)
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, str) and first.strip():
                return base64.b64decode(first)

    raise VolcengineTTSError(
        "Volcengine TTS response missing audio data",
        error_kind="tts_parse_error",
    )


class VolcengineCloneTTSProvider(TTSProvider):
    """HTTP TTS via Volcengine OpenSpeech voice clone API."""

    def __init__(self, config: ResolvedTtsConfig) -> None:
        self.config = config

    def _build_payload(self, text: str, reqid: str) -> dict[str, Any]:
        return {
            "app": {"cluster": self.config.cluster},
            "user": {"uid": self.config.uid},
            "audio": {
                "voice_type": self.config.voice_type,
                "encoding": self.config.encoding,
                "speed_ratio": self.config.speed_ratio,
            },
            "request": {
                "reqid": reqid,
                "text": text,
                "operation": "query",
            },
        }

    async def synthesize(self, text: str, output_path: Path) -> Path:
        if not text.strip():
            raise ValueError("TTS text cannot be empty.")

        output_path = output_path.expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        reqid = uuid.uuid4().hex
        payload = self._build_payload(text.strip(), reqid)
        timeout = httpx.Timeout(_tts_timeout(), connect=_tts_connect_timeout())

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                self.config.api_url,
                headers={
                    "x-api-key": self.config.api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        if response.status_code >= 400:
            raise VolcengineTTSError(
                f"Volcengine TTS HTTP {response.status_code}: {response.text[:500]}",
                error_kind="tts_http_error",
                status_code=response.status_code,
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise VolcengineTTSError(
                "Volcengine TTS returned non-JSON response",
                error_kind="tts_parse_error",
            ) from exc

        audio_bytes = _extract_audio_bytes(body)
        encoding = (self.config.encoding or "mp3").lower()
        target_suffix = output_path.suffix.lower().lstrip(".")

        if target_suffix == "wav" and encoding != "wav":
            await asyncio.to_thread(
                _write_mp3_then_convert_wav,
                audio_bytes,
                output_path,
            )
        else:
            output_path.write_bytes(audio_bytes)

        return output_path


def _write_mp3_then_convert_wav(mp3_bytes: bytes, output_path: Path) -> None:
    import tempfile

    from pydub import AudioSegment

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        tmp_path.write_bytes(mp3_bytes)
        audio = AudioSegment.from_file(str(tmp_path), format="mp3")
        audio.export(str(output_path), format="wav")
    finally:
        tmp_path.unlink(missing_ok=True)
