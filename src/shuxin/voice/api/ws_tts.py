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
MAX_STREAMING_TTS_CHARS = 72
MIN_WEAK_SPLIT_CHARS = 40


def _elapsed_ms(start_time: float) -> int:
    return int((time.perf_counter() - start_time) * 1000)


def _sentence_path(base_path: Path, sentence_index: int) -> Path:
    if sentence_index == 1:
        return base_path
    return base_path.with_name(f"{base_path.stem}-{sentence_index:03d}{base_path.suffix}")


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
                    if (
                        allow_weak_punctuation
                        and char in FIRST_SEGMENT_WEAK_DELIMITERS
                        and index + 1 < MIN_WEAK_SPLIT_CHARS
                    ):
                        continue
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

    async def render_sentence(
        self,
        text: str,
        base_path: Path,
        sentence_index: int,
    ) -> Path:
        output_path = _sentence_path(base_path, sentence_index)
        clean_text = prepare_speakable_text(text)
        if not clean_text:
            output_path.write_bytes(b"")
            return output_path
        return await self.session.tts.synthesize(clean_text, output_path)

    async def emit_sentence(
        self,
        text: str,
        speech_path: Path,
        sentence_index: int,
        turn_started: float,
    ) -> Path:
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
            return speech_path

        try:
            sentence_started = time.perf_counter()
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
            logger.warning("TTS 语音下发失败 (text='%s'): %s", clean_text, exc)
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
            return speech_path

    async def synthesize_and_send(
        self,
        text: str,
        base_path: Path,
        sentence_index: int,
        turn_started: float,
    ) -> Path:
        """合成单句文本并实时发送音频。如果全是括弧动作文本，服务端静默忽略合成但会发送控制事件。"""
        try:
            speech_path = await self.render_sentence(text, base_path, sentence_index)
        except Exception as exc:
            logger.warning("TTS 语音合成失败 (text='%s'): %s", text, exc)
            speech_path = _sentence_path(base_path, sentence_index)
            try:
                speech_path.write_bytes(b"")
            except Exception:
                pass
        return await self.emit_sentence(text, speech_path, sentence_index, turn_started)

    async def consume_with_prefetch(
        self,
        queue: asyncio.Queue,
        base_path: Path,
        turn_started: float,
        state: dict[str, Any],
    ) -> None:
        """LLM 继续吐字的同时预合成下一句，避免句间停顿。"""
        pending = await queue.get()
        if pending is None:
            return

        async def begin() -> None:
            if not state["started"]:
                state["started"] = time.perf_counter()
                await self.session._send_json({"type": "tts", "state": "start"})

        async def mark(path: Path) -> None:
            state["path"] = path
            started = float(state["started"] or time.perf_counter())
            state["total_ms"] = _elapsed_ms(started)
            if state["first_audio_ms"] is None:
                state["first_audio_ms"] = _elapsed_ms(turn_started)

        ready_text = pending
        state["index"] = int(state.get("index") or 0) + 1
        ready_idx = int(state["index"])
        ready_task: asyncio.Task = asyncio.create_task(
            self.render_sentence(ready_text, base_path, ready_idx)
        )

        while True:
            try:
                rendered = await ready_task
            except Exception as exc:
                logger.warning("TTS 预合成失败 (text='%s'): %s", ready_text, exc)
                rendered = _sentence_path(base_path, ready_idx)
                try:
                    rendered.write_bytes(b"")
                except Exception:
                    pass
            await begin()
            try:
                nxt = queue.get_nowait()
            except asyncio.QueueEmpty:
                emit_task = asyncio.create_task(
                    self.emit_sentence(ready_text, rendered, ready_idx, turn_started)
                )
                nxt = await queue.get()
                if nxt is not None:
                    state["index"] = int(state["index"]) + 1
                    next_idx = int(state["index"])
                    ready_task = asyncio.create_task(
                        self.render_sentence(nxt, base_path, next_idx)
                    )
                    ready_text = nxt
                    ready_idx = next_idx
                await mark(await emit_task)
                if nxt is None:
                    return
                continue

            if nxt is None:
                await mark(
                    await self.emit_sentence(ready_text, rendered, ready_idx, turn_started)
                )
                return

            state["index"] = int(state["index"]) + 1
            next_idx = int(state["index"])
            ready_task = asyncio.create_task(
                self.render_sentence(nxt, base_path, next_idx)
            )
            await mark(
                await self.emit_sentence(ready_text, rendered, ready_idx, turn_started)
            )
            ready_text = nxt
            ready_idx = next_idx
