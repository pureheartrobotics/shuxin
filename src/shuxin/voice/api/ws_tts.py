from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from shuxin.voice.audio.text_sanitize import has_unclosed_parenthesis, prepare_speakable_text

if TYPE_CHECKING:
    from shuxin.voice.api.ws_session import _VoiceWebSocketSession

logger = logging.getLogger("shuxin.voice.api.ws_tts")

SENTENCE_DELIMITERS = "。！？!?；;\n"
FIRST_SEGMENT_WEAK_DELIMITERS = "，,、"
MAX_STREAMING_TTS_CHARS = 48


def _elapsed_ms(start_time: float) -> int:
    return int((time.perf_counter() - start_time) * 1000)


class TtsSentenceSegmenter:
    """包装语音合成（TTS）的分句切割、括号文本过滤与音频分发管道。"""

    def __init__(self, session: _VoiceWebSocketSession) -> None:
        self.session = session

    def pop_segments(
        self,
        buffer: str,
        *,
        force: bool = False,
        allow_weak_punctuation: bool = False,
    ) -> tuple[list[str], str]:
        """将 LLM 输出流中的文本切割成适合低延迟合成的完整句子。"""
        delimiters = SENTENCE_DELIMITERS
        if allow_weak_punctuation:
            delimiters += FIRST_SEGMENT_WEAK_DELIMITERS
        segments: list[str] = []
        while buffer:
            cut_at = -1
            in_parentheses = False
            for index, char in enumerate(buffer):
                if char in ("（", "("):
                    in_parentheses = True
                elif char in ("）", ")"):
                    in_parentheses = False
                elif char in delimiters and not in_parentheses:
                    cut_at = index + 1
                    break
            if cut_at < 0 and force:
                cut_at = len(buffer)
            if (
                cut_at < 0
                and len(buffer) >= MAX_STREAMING_TTS_CHARS
                and not has_unclosed_parenthesis(buffer)
            ):
                cut_at = MAX_STREAMING_TTS_CHARS
            if cut_at < 0:
                break
            segment = buffer[:cut_at].strip()
            buffer = buffer[cut_at:]
            if segment:
                segments.append(segment)
        return segments, buffer

    async def synthesize_and_send(
        self,
        text: str,
        base_path: Path,
        sentence_index: int,
        turn_started: float,
    ) -> Path:
        """合成单句文本并实时发送音频。如果全是括弧动作文本，服务端静默忽略合成但会发送控制事件。"""
        if sentence_index == 1:
            output_path = base_path
        else:
            output_path = base_path.with_name(
                f"{base_path.stem}-{sentence_index:03d}{base_path.suffix}"
            )
        await self.session._send_json(
            {
                "type": "tts",
                "state": "sentence_start",
                "text": text,
                "index": sentence_index,
                "total_elapsed_ms": _elapsed_ms(turn_started),
            }
        )
        clean_text = prepare_speakable_text(text)
        if not clean_text:
            output_path.write_bytes(b"")
            await asyncio.sleep(0.01)
            await self.session._send_json(
                {
                    "type": "tts",
                    "state": "sentence_stop",
                    "text": text,
                    "index": sentence_index,
                    "elapsed_ms": 10,
                    "total_elapsed_ms": _elapsed_ms(turn_started),
                }
            )
            return output_path

        try:
            sentence_started = time.perf_counter()
            speech_path = await self.session.tts.synthesize(clean_text, output_path)
            if self.session._uses_opus_downlink():
                await self.session._send_opus_downlink_stream(speech_path)
            else:
                await self.session._send_downlink_bytes(speech_path.read_bytes())
            await self.session._send_json(
                {
                    "type": "tts",
                    "state": "sentence_stop",
                    "text": text,
                    "index": sentence_index,
                    "elapsed_ms": _elapsed_ms(sentence_started),
                    "total_elapsed_ms": _elapsed_ms(turn_started),
                }
            )
            return speech_path
        except Exception as exc:
            logger.warning("TTS 语音合成失败 (clean_text='%s'): %s", clean_text, exc)
            try:
                output_path.write_bytes(b"")
            except Exception:
                pass
            await self.session._send_json(
                {
                    "type": "tts",
                    "state": "sentence_stop",
                    "text": text,
                    "index": sentence_index,
                    "elapsed_ms": 10,
                    "total_elapsed_ms": _elapsed_ms(turn_started),
                }
            )
            return output_path
