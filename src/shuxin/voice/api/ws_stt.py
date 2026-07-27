from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from shuxin.voice.integrations.tencent_realtime_asr import (
    TencentRealtimeASRResult,
    TencentRealtimeASRSession,
    is_tencent_realtime_stt,
)

if TYPE_CHECKING:
    from shuxin.voice.api.ws_session import _VoiceWebSocketSession

logger = logging.getLogger("shuxin.voice.api.ws_stt")


def _elapsed_ms(start_time: float) -> int:
    return int((time.perf_counter() - start_time) * 1000)


class SpeechTranscriber:
    """封装实时语音识别（ASR）的交互管理层。"""

    def __init__(self, session: _VoiceWebSocketSession) -> None:
        self.session = session
        self.realtime_asr: TencentRealtimeASRSession | None = None
        self.realtime_stt_started: float = 0.0

    async def start(self) -> str:
        """在录音开始时启动腾讯云实时 ASR。返回 started|skipped。"""
        if self.session._agent_init_task is not None:
            await self.session._agent_init_task
        if self.session.device is None:
            self.session.device = await self.session.repo.get_device(self.session.device_id)
        if self.session.device is None or not is_tencent_realtime_stt(self.session.device.stt):
            logger.info(
                "[SOFT-VOICE] asr_skip device=%s reason=not_tencent_realtime",
                self.session.device_id,
            )
            return "skipped"
        if self.realtime_asr is not None:
            await self.realtime_asr.close()
        self.realtime_stt_started = time.perf_counter()
        self.realtime_asr = TencentRealtimeASRSession(
            self.session.device.stt,
            on_result=self._handle_realtime_asr_result,
            on_end=self._handle_realtime_asr_end,
        )
        await self.realtime_asr.start()
        await self.session._send_json({"type": "stt", "state": "stream_start"})
        logger.info(
            "[SOFT-VOICE] asr_started device=%s client=%s",
            self.session.device_id,
            self.session.client_id,
        )
        return "started"

    async def send_audio(self, pcm_frame: bytes) -> None:
        """向上行 ASR 音频流发送 PCM 数据块。"""
        if self.realtime_asr is not None:
            await self.realtime_asr.send_audio(pcm_frame)

    async def finish(self) -> str | None:
        """结束 ASR 传输，返回识别出的最终文本内容。"""
        if self.realtime_asr is not None:
            try:
                text = await self.realtime_asr.finish()
                logger.info(
                    "[SOFT-VOICE] asr_finish text_len=%s device=%s",
                    len(text or ""),
                    self.session.device_id,
                )
                return text
            finally:
                self.realtime_asr = None
        return None

    async def close(self) -> None:
        """强制中断/异常关闭 ASR 连接。"""
        if self.realtime_asr is not None:
            await self.realtime_asr.close()
            self.realtime_asr = None

    async def _handle_realtime_asr_end(self, reason: str, text: str) -> None:
        cleaned = str(text or "").strip()
        logger.info(
            "[SOFT-VOICE] asr_%s last_text_len=%s device=%s",
            reason,
            len(cleaned),
            self.session.device_id,
        )
        if reason == "idle" and cleaned:
            asyncio.create_task(
                self.session._trigger_continuous_turn(
                    cleaned,
                    source="asr_idle_fallback",
                )
            )

    async def _handle_realtime_asr_result(
        self,
        result: TencentRealtimeASRResult,
    ) -> None:
        """把腾讯云实时 ASR 的中间/稳定结果转发给前端。"""
        state = "partial"
        if result.is_sentence_final:
            state = "sentence_final"
        if result.is_stream_final:
            state = "stream_final"
        text = str(result.text or "")
        if state in {"sentence_final", "stream_final"}:
            logger.info(
                "[SOFT-VOICE] asr %s text_len=%s device=%s",
                state,
                len(text.strip()),
                self.session.device_id,
            )
        await self.session._send_json(
            {
                "type": "stt",
                "state": state,
                "text": result.text,
                "elapsed_ms": _elapsed_ms(self.realtime_stt_started),
            }
        )
        if result.is_sentence_final and text.strip():
            asyncio.create_task(
                self.session._trigger_continuous_turn(
                    text,
                    source="sentence_final",
                )
            )
