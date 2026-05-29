from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from urllib.parse import quote, urlencode

from shuxin.voice.config import ProviderConfig

ASR_HOST = "asr.cloud.tencent.com"
ASR_PATH_TEMPLATE = "/asr/v2/{appid}"
PCM_16K_200MS_BYTES = 6400


@dataclass
class TencentRealtimeASRResult:
    text: str = ""
    final_text: str = ""
    is_sentence_final: bool = False
    is_stream_final: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


def is_tencent_realtime_stt(config: ProviderConfig) -> bool:
    return (config.type or "").lower() in {"tencent-realtime", "tencent-asr-realtime"}


def build_tencent_realtime_asr_url(
    config: ProviderConfig,
    *,
    voice_id: str | None = None,
    now: int | None = None,
) -> str:
    """Build a signed Tencent Cloud realtime ASR WebSocket URL."""
    appid = os.environ.get("TENCENT_ASR_APPID") or config.appid or config.api_url
    secret_id = os.environ.get("TENCENTCLOUD_SECRET_ID")
    secret_key = os.environ.get("TENCENTCLOUD_SECRET_KEY") or config.api_key
    if not appid:
        raise RuntimeError("Tencent realtime ASR requires TENCENT_ASR_APPID.")
    if not secret_id:
        raise RuntimeError("Tencent realtime ASR requires TENCENTCLOUD_SECRET_ID.")
    if not secret_key:
        raise RuntimeError("Tencent realtime ASR requires TENCENTCLOUD_SECRET_KEY.")

    started = int(now if now is not None else time.time())
    path = ASR_PATH_TEMPLATE.format(appid=appid)
    params: dict[str, str | int] = {
        "convert_num_mode": 1,
        "engine_model_type": config.model or "16k_zh",
        "expired": started + 24 * 60 * 60,
        "filter_dirty": 0,
        "filter_modal": 0,
        "filter_punc": 0,
        "needvad": 1,
        "nonce": random.randint(1, 1_000_000_000),
        "secretid": secret_id,
        "timestamp": started,
        "voice_format": 1,
        "voice_id": voice_id or uuid.uuid4().hex,
        "word_info": 0,
    }
    query = urlencode(sorted(params.items()))
    sign_content = f"{ASR_HOST}{path}?{query}"
    digest = hmac.new(
        secret_key.encode("utf-8"),
        sign_content.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    signature = quote(base64.b64encode(digest).decode("utf-8"), safe="")
    return f"wss://{sign_content}&signature={signature}"


def parse_tencent_realtime_asr_message(payload: str) -> TencentRealtimeASRResult:
    data = json.loads(payload)
    if int(data.get("code", 0) or 0) != 0:
        message = data.get("message") or data.get("error") or payload
        raise RuntimeError(f"Tencent realtime ASR failed: {message}")

    result = data.get("result")
    if not isinstance(result, dict):
        result = {}

    text = str(
        result.get("voice_text_str")
        or result.get("text")
        or data.get("voice_text_str")
        or data.get("text")
        or ""
    )
    slice_type = int(result.get("slice_type", data.get("slice_type", 0)) or 0)
    final_flag = int(data.get("final", 0) or 0) == 1
    return TencentRealtimeASRResult(
        text=text,
        final_text=text if slice_type == 2 else "",
        is_sentence_final=slice_type == 2,
        is_stream_final=final_flag,
        raw=data,
    )


class TencentRealtimeASRSession:
    """Small WebSocket bridge for Tencent Cloud realtime ASR."""

    def __init__(
        self,
        config: ProviderConfig,
        *,
        on_result: Callable[[TencentRealtimeASRResult], Awaitable[None]],
        chunk_bytes: int = PCM_16K_200MS_BYTES,
    ) -> None:
        self.config = config
        self.on_result = on_result
        self.chunk_bytes = chunk_bytes
        self._websocket = None
        self._reader_task: asyncio.Task | None = None
        self._buffer = bytearray()
        self._final_parts: list[str] = []
        self._last_text = ""

    @property
    def final_text(self) -> str:
        return ("".join(self._final_parts) or self._last_text).strip()

    async def start(self) -> None:
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError(
                "Tencent realtime ASR requires the websockets package."
            ) from exc

        self._websocket = await websockets.connect(
            build_tencent_realtime_asr_url(self.config),
            max_size=8 * 1024 * 1024,
        )
        self._reader_task = asyncio.create_task(self._read_loop())

    async def send_audio(self, frame: bytes) -> None:
        if self._websocket is None or not frame:
            return
        self._buffer.extend(frame)
        while len(self._buffer) >= self.chunk_bytes:
            chunk = bytes(self._buffer[: self.chunk_bytes])
            del self._buffer[: self.chunk_bytes]
            await self._websocket.send(chunk)

    async def finish(self) -> str:
        if self._websocket is None:
            return self.final_text
        if self._buffer:
            await self._websocket.send(bytes(self._buffer))
            self._buffer.clear()
        await self._websocket.send(json.dumps({"type": "end"}))
        if self._reader_task is not None:
            await self._reader_task
        await self._websocket.close()
        self._websocket = None
        return self.final_text

    async def close(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._websocket is not None:
            await self._websocket.close()
            self._websocket = None
        self._buffer.clear()

    async def _read_loop(self) -> None:
        assert self._websocket is not None
        async for message in self._websocket:
            if isinstance(message, bytes):
                continue
            result = parse_tencent_realtime_asr_message(message)
            if result.text:
                self._last_text = result.text
            if result.is_sentence_final and result.final_text:
                self._final_parts.append(result.final_text)
            await self.on_result(result)
            if result.is_stream_final:
                break
