from __future__ import annotations

from typing import Any, Optional, Dict, List
from fastapi import WebSocket, WebSocketDisconnect
import argparse
import re
import asyncio
import json
import logging
import os
import threading
import uuid
import time
from pathlib import Path

from shuxin.core.agent import Agent, ToolLoopCallbacks
from shuxin.core.config import get_shuxin_home
from shuxin.integrations.location import format_location_context_block, get_location_provider, may_need_location
from shuxin.integrations.location.ip_resolve import resolve_effective_ip
from shuxin.core.identity import IdentityEngine, load_mbti_profiles
from shuxin.voice.integrations.adapters import VoiceAdapterRegistry
from shuxin.voice.audio.audio_files import AudioFileStore
from shuxin.voice.integrations.barcode import decode_barcode_image_base64, generate_code128_png
from shuxin.voice.config.config import DeviceConfigProvider, LLMDeviceConfig, merge_llm_device_config
from shuxin.voice.integrations.dmx_client import (
    QUOTA_EXHAUSTED_MESSAGE,
    default_platform_llm_config,
    voice_test_mode_enabled,
)
from shuxin.voice.persistence.db import PostgresDatabase
from shuxin.voice.persistence.local_repository import VoiceLocalRepository
from shuxin.voice.persistence.postgres_repository import VoicePostgresRepository
from shuxin.voice.audio.opus_codec import (
    DEFAULT_CHANNELS,
    DEFAULT_FRAME_DURATION_MS,
    DOWNLINK_SAMPLE_RATE,
    OpusStreamDecoder,
    UPLINK_SAMPLE_RATE,
    iter_transcode_mp3_to_opus_frames,
    looks_like_mp3,
    opus_available,
)
from shuxin.voice.providers import create_stt_provider
from shuxin.voice.persistence.agents import DEFAULT_AGENT_ID
from shuxin.voice.config.tts_config import create_tts_provider_from_agent, create_tts_provider_from_device
from shuxin.voice.config.mbti_reveal import (
    build_device_intro_text,
    build_factory_verify_mbti_payload,
    needs_device_intro,
    needs_mbti_reveal,
)
from shuxin.voice.api import voice_session_registry as vsr
from shuxin.voice.api.ws_stt import SpeechTranscriber
from shuxin.voice.api.ws_llm import LlmStreamProcessor
from shuxin.voice.api.ws_tts import TtsSentenceSegmenter
from shuxin.voice.api.miniapp_admin import miniapp_admin_router
from shuxin.voice.api.routers.exception_handlers import register_exception_handlers
from shuxin.voice.api.routers.user import router as user_router
from shuxin.voice.api.routers.payment import router as payment_router
from shuxin.voice.api.routers.factory import router as factory_router
from shuxin.voice.api.routers.admin import router as admin_router
from shuxin.voice.service import VoiceService
from shuxin.voice.audio.text_sanitize import has_unclosed_parenthesis, prepare_speakable_text
from shuxin.voice.integrations.tencent_realtime_asr import (
    TencentRealtimeASRResult,
    TencentRealtimeASRSession,
    is_tencent_realtime_stt,
)
from shuxin.voice.persistence.users import DEFAULT_USER_ID, UserConfigProvider

# WebSocket 上行音频统一按 16kHz / mono / PCM16 处理。
# 浏览器测试台和后续硬件只需要发送裸 PCM 帧，不需要封装 wav 头。
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
CHANNELS = 1
SENTENCE_DELIMITERS = "。！？!?；;\n"
FIRST_SEGMENT_WEAK_DELIMITERS = "，,、"
MAX_STREAMING_TTS_CHARS = 48

DEFAULT_AUDIO_RETENTION_HOURS = 12
DEFAULT_AUDIO_RETENTION_INTERVAL_SEC = 1800
DEFAULT_FACTORY_VERIFY_LOG_RETENTION_DAYS = 15
DEFAULT_LOCATION_CACHE_TTL_SECONDS = 1800
FACTORY_VERIFY_ACK_TIMEOUT_SECONDS = 10.0
DEFAULT_WS_DOWNLINK_MAX_BYTES = 2048
HARD_WS_DOWNLINK_MAX_BYTES = 4096
logger = logging.getLogger("shuxin.voice.server")
_FACTORY_ACCEPTANCE_DISABLED = "factory acceptance mode: conversation disabled"
def _location_cache_ttl_seconds() -> int:
    raw = os.environ.get(
        "SHUXIN_LOCATION_CACHE_TTL_SECONDS",
        str(DEFAULT_LOCATION_CACHE_TTL_SECONDS),
    ).strip()
    try:
        return max(60, int(raw))
    except ValueError:
        return DEFAULT_LOCATION_CACHE_TTL_SECONDS


def _ws_downlink_max_bytes() -> int:
    raw = int(os.environ.get("SHUXIN_WS_DOWNLINK_MAX_BYTES", DEFAULT_WS_DOWNLINK_MAX_BYTES))
    return max(256, min(raw, HARD_WS_DOWNLINK_MAX_BYTES))


def _ws_downlink_yield_seconds() -> float:
    raw = float(os.environ.get("SHUXIN_WS_DOWNLINK_YIELD_MS", "0"))
    return max(0.0, raw) / 1000.0






def _negotiate_audio_params(client_params: dict | None) -> dict[str, int | str]:
    params = client_params if isinstance(client_params, dict) else {}
    fmt = str(params.get("format") or "pcm").strip().lower()
    if fmt not in {"pcm", "opus"}:
        fmt = "pcm"
    frame_duration = int(params.get("frame_duration") or DEFAULT_FRAME_DURATION_MS)
    if frame_duration <= 0:
        frame_duration = DEFAULT_FRAME_DURATION_MS
    if fmt == "opus":
        return {
            "format": "opus",
            "uplink_sample_rate": UPLINK_SAMPLE_RATE,
            "downlink_sample_rate": DOWNLINK_SAMPLE_RATE,
            "channels": DEFAULT_CHANNELS,
            "frame_duration": frame_duration,
        }
    return {
        "format": "pcm",
        "uplink_sample_rate": UPLINK_SAMPLE_RATE,
        "downlink_sample_rate": UPLINK_SAMPLE_RATE,
        "channels": DEFAULT_CHANNELS,
        "frame_duration": frame_duration,
    }




def _client_ip_from_websocket(websocket) -> str:
    """从 WebSocket 连接解析客户端 IP（支持 X-Forwarded-For）。"""
    headers = getattr(websocket, "headers", None)
    forwarded = None
    if headers is not None and hasattr(headers, "get"):
        forwarded = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")
    if forwarded:
        return str(forwarded).split(",")[0].strip()
    client = getattr(websocket, "client", None)
    if client is not None:
        return str(getattr(client, "host", "") or "")
    return ""


class _VoiceWebSocketSession:
    """单条 WebSocket 连接的运行态。

    一个连接会绑定 user_id、device_id、client_id 和 session_id。
    同一个用户的多台设备共享长期记忆目录，但每轮音频附件仍按
    user/device/session 分层保存，方便后续做额度控制和事件回放。
    """

    def __init__(
        self,
        websocket,
        service: VoiceService,
        repo,
        shuxin_home: Path,
        default_device_id: str,
        out_dir: Path,
        app=None,
    ):
        self.websocket = websocket
        self.service = service
        self.repo = repo
        self.shuxin_home = shuxin_home
        self.default_device_id = default_device_id
        self.out_dir = out_dir
        self.app = app
        self.user_id = DEFAULT_USER_ID
        self.user_settings = None
        self.audio_store: AudioFileStore | None = None
        self.session_id = ""
        self.device_id = default_device_id
        self.client_id = "web-demo"
        self.device = None
        self.stt = None
        self.tts = None
        self.agent = None
        self.agent_record = None
        self.audio_chunks: list[bytes] = []
        self.listening = False
        self.audio_wire_format = "pcm"
        self.audio_params: dict[str, int | str] = _negotiate_audio_params(None)
        self.opus_uplink_decoder: OpusStreamDecoder | None = None
        self.hardware_session = False
        self.factory_acceptance = False
        self.client_ip = _client_ip_from_websocket(websocket)
        self._location_cache: dict | None = None
        self._agent_init_task: Optional[asyncio.Task] = None
        self.companion_id: Optional[str] = None

        # 初始化独立管道处理器
        self.stt_pipeline = SpeechTranscriber(self)
        self.llm_pipeline = LlmStreamProcessor(self)
        self.tts_pipeline = TtsSentenceSegmenter(self)

        # 消息映射表
        self.handlers = {
            "hello": self._handle_hello_msg,
            "listen": self._handle_listen_msg,
            "abort": self._handle_abort_msg,
            "text_turn": self._handle_text_turn_msg,
            "factory_verify_ack": self._handle_factory_verify_ack_msg,
            "ping": self._handle_ping_msg,
        }

    async def run(self) -> None:
        """进入消息循环，按文本控制消息和二进制音频帧分流处理。"""
        await self._send_json(
            {"type": "hello", "state": "ready", "device_id": self.device_id}
        )

        while True:
            message = await self.websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if "text" in message:
                await self._handle_text(message["text"])
            elif "bytes" in message:
                await self._handle_audio_frame(message["bytes"])

    async def shutdown(self, mark_offline: bool = True) -> None:
        """关闭连接时释放当前 Agent，避免插件状态和资源泄漏。"""
        if self._agent_init_task is not None:
            self._agent_init_task.cancel()
            self._agent_init_task = None
        if self.user_settings is not None:
            try:
                await self.repo.maybe_merge_rolling_summary(
                    self.user_settings,
                    self.device,
                    force=True,
                )
            except Exception:
                pass
        await self.stt_pipeline.close()
        if self.agent is not None:
            await asyncio.to_thread(self.agent.shutdown)
            self.agent = None
        self.agent_record = None
        if mark_offline and self.device_id:
            try:
                await self.repo.touch_device_status(device_id=self.device_id, online=False)
            except Exception:
                pass
        if self.device_id:
            vsr.unregister(self.device_id, self)

    async def _handle_text(self, raw: str) -> None:
        """处理设备/浏览器上行的 JSON 控制消息。

        `hello` 决定用户身份和设备配置；`listen start/stop` 决定一轮
        语音采集边界；`abort` 清空当前轮缓存；`ping` 用于连接保活。
        """
        data = json.loads(raw)
        message_type = data.get("type")

        # 拦截未经过成功 hello 鉴权就直接发起对话的连接
        if message_type in {"listen", "text_turn"} and not self.user_settings:
            await self._send_json(
                {
                    "type": "error",
                    "message": "WebSocket session is not authenticated. Please select target and connect first.",
                }
            )
            return

        if self.factory_acceptance and message_type in {"listen", "text_turn"}:
            await self._send_json({"type": "error", "message": _FACTORY_ACCEPTANCE_DISABLED})
            return

        if isinstance(message_type, str) and message_type.startswith("call/"):
            from shuxin.integrations.voice_call.dispatch import handle_device_call_message

            await handle_device_call_message(self, data)
            return

        handler = self.handlers.get(message_type)
        if handler:
            await handler(data)
        else:
            await self._send_json({"type": "error", "message": f"unsupported message: {data}"})

    async def _handle_hello_msg(self, data: dict[str, Any]) -> None:
        factory_acceptance = False
        try:
            if data.get("device_code") or data.get("device_secret"):
                device_code = (
                    data.get("device_code") or data.get("device_id") or self.default_device_id
                )
                device_secret = data.get("device_secret") or ""
                try:
                    self.user_settings = await self.repo.authenticate_device(
                        device_code,
                        device_secret,
                    )
                except PermissionError as exc:
                    if "not bound" in str(exc).lower():
                        self.user_settings = await self.repo.authenticate_device_for_factory(
                            device_code,
                            device_secret,
                        )
                        factory_acceptance = True
                    else:
                        raise
            else:
                self.user_settings = await self.repo.authenticate_user(
                    data.get("user_id") or DEFAULT_USER_ID,
                    data.get("token") or "",
                )
        except Exception as exc:
            await self._send_json({"type": "error", "message": str(exc)})
            return
        self.factory_acceptance = factory_acceptance
        self.user_id = self.user_settings.user_id
        self.device_id = (
            data.get("device_code")
            or data.get("device_id")
            or self.default_device_id
        )
        self.client_id = data.get("client_id") or "web-demo"
        self.companion_id = str(data.get("companion_id") or "").strip() or None
        self.audio_store = AudioFileStore(self.shuxin_home, self.out_dir, self.user_id)
        self.session_id = data.get("session_id") or uuid.uuid4().hex
        if not self.factory_acceptance:
            asyncio.create_task(
                self.repo.ensure_session(
                    session_id=self.session_id,
                    user_id=self.user_id,
                    device_id=self.device_id,
                    client_id=self.client_id,
                )
            )
        asyncio.create_task(
            self.repo.touch_device_status(
                device_id=self.device_id,
                online=True,
                session_id=self.session_id,
            )
        )
        self.hardware_session = bool(data.get("device_code") or data.get("device_secret"))
        self.audio_params = _negotiate_audio_params(data.get("audio_params"))
        if (
            self.hardware_session
            and not self._is_web_demo_client()
            and self.audio_params["format"] != "opus"
        ):
            logger.warning(
                "hardware session requested %s wire format; forcing opus",
                self.audio_params["format"],
            )
            self.audio_params = _negotiate_audio_params(
                {"format": "opus", "frame_duration": self.audio_params["frame_duration"]}
            )
        self.audio_wire_format = str(self.audio_params["format"])
        self.opus_uplink_decoder = None
        if self.audio_wire_format == "opus":
            if not opus_available():
                await self._send_json(
                    {
                        "type": "error",
                        "message": "opus support requires opuslib_next (requirements-voice-app.txt); redeploy Docker",
                    }
                )
                return
            self.opus_uplink_decoder = OpusStreamDecoder(
                sample_rate=int(self.audio_params["uplink_sample_rate"]),
                frame_duration_ms=int(self.audio_params["frame_duration"]),
            )
        await self._reset_runtime()
        hello_ok = {
            "type": "hello",
            "state": "ok",
            "user_id": self.user_id,
            "device_id": self.device_id,
            "client_id": self.client_id,
            "session_id": self.session_id,
        }
        if self.factory_acceptance:
            hello_ok["factory_acceptance"] = True
        if self.audio_wire_format == "opus":
            hello_ok["audio_params"] = {
                "format": "opus",
                "uplink_sample_rate": int(self.audio_params["uplink_sample_rate"]),
                "downlink_sample_rate": int(self.audio_params["downlink_sample_rate"]),
                "channels": int(self.audio_params["channels"]),
                "frame_duration": int(self.audio_params["frame_duration"]),
            }
        await self._send_json(hello_ok)
        vsr.register(self.device_id, self)
        if not self.factory_acceptance:
            self._agent_init_task = asyncio.create_task(self._ensure_runtime())

            async def run_mbti_reveal():
                try:
                    await self._maybe_reveal_mbti_on_hello()
                except Exception as exc:
                    logger.warning("mbti reveal on hello failed: %s", exc)
            asyncio.create_task(run_mbti_reveal())

    async def _handle_listen_msg(self, data: dict[str, Any]) -> None:
        state = data.get("state")
        if state == "start":
            self.audio_chunks = []
            self.listening = True
            try:
                await self._start_realtime_asr_if_needed()
            except Exception as exc:
                self.listening = False
                await self._send_json({"type": "error", "message": str(exc)})
                return
            await self._send_json({"type": "listen", "state": "start"})
        elif state == "stop":
            self.listening = False
            await self._process_turn()

    async def _handle_abort_msg(self, data: dict[str, Any]) -> None:
        self.audio_chunks = []
        self.listening = False
        await self.stt_pipeline.close()
        await self._send_json({"type": "abort", "state": "ok"})

    async def _handle_text_turn_msg(self, data: dict[str, Any]) -> None:
        if os.environ.get("SHUXIN_VOICE_DEV_TEXT_TURN") != "1":
            await self._send_json(
                {"type": "error", "message": "text_turn disabled (set SHUXIN_VOICE_DEV_TEXT_TURN=1)"}
            )
            return
        text = str(data.get("text") or "").strip()
        if not text:
            await self._send_json({"type": "error", "message": "text_turn requires text"})
            return
        await self._process_text_turn(text)

    async def _handle_factory_verify_ack_msg(self, data: dict[str, Any]) -> None:
        verify_id = str(data.get("verify_id") or "")
        if self.device_id and vsr.factory_verify_ack(self.device_id):
            logger.info(
                "factory_verify_ack received device=%s verify_id=%s",
                self.device_id,
                verify_id,
            )
        else:
            logger.warning(
                "factory_verify_ack ignored (no pending verify) device=%s verify_id=%s",
                self.device_id,
                verify_id,
            )

    async def _handle_ping_msg(self, data: dict[str, Any]) -> None:
        await self._send_json({"type": "pong", "ts": time.time()})

    async def _start_realtime_asr_if_needed(self) -> None:
        """运行态实时 ASR 启动代理。"""
        await self.stt_pipeline.start()

    async def _handle_audio_frame(self, frame: bytes) -> None:
        """缓存 listen 窗口内收到的 PCM16 或 Opus 二进制音频帧，并按需转发实时 ASR。"""
        if self.listening and frame:
            pcm_frame = frame
            if self.audio_wire_format == "opus":
                if self.opus_uplink_decoder is None:
                    self.opus_uplink_decoder = OpusStreamDecoder(
                        sample_rate=int(self.audio_params["uplink_sample_rate"]),
                        frame_duration_ms=int(self.audio_params["frame_duration"]),
                    )
                pcm_frame = self.opus_uplink_decoder.decode_packet(frame)
            self.audio_chunks.append(pcm_frame)
            await self.stt_pipeline.send_audio(pcm_frame)

    async def _process_turn(self) -> None:
        """处理完整的一轮语音对话。

        流程是: PCM 帧落盘为 wav -> STT -> Agent 文本回复 -> TTS ->
        mp3 下发 -> 事件和附件索引入库。第一版是 turn-based 准实时，
        即用户松手后才开始识别和回复。
        """
        if not self.audio_chunks:
            await self._send_json({"type": "error", "message": "no audio received"})
            return

        started = time.perf_counter()
        pcm = b"".join(self.audio_chunks)

        try:
            await self._assert_quota_for_turn()
            await self._ensure_runtime()
            assert self.audio_store is not None
            assert self.user_settings is not None
            paths = self.audio_store.new_turn_paths(self.device_id, self.session_id or None)
            self.session_id = paths.session_id
            self.audio_store.write_input_wav(pcm, paths.input_wav)
            await self._send_json({"type": "stt", "state": "start"})
            stt_started = time.perf_counter()
            if self.stt_pipeline.realtime_asr is not None:
                text = (await self.stt_pipeline.finish()) or ""
            else:
                text = await self.stt.transcribe(paths.input_wav)
            stt_ms = _elapsed_ms(stt_started)
            await self._send_json(
                {"type": "stt", "state": "final", "text": text, "elapsed_ms": stt_ms}
            )

            from shuxin.integrations.voice_call.dispatch import try_dispatch_call_intent

            handled, call_reply = await try_dispatch_call_intent(self, text)
            if handled:
                await self._send_json(
                    {"type": "agent", "state": "reply", "text": call_reply, "elapsed_ms": 0}
                )
                await self._send_json({"type": "tts", "state": "start"})
                speech_path = await self.tts_pipeline.synthesize_and_send(
                    call_reply,
                    paths.reply_mp3,
                    1,
                    started,
                )
                tts_total_ms = _elapsed_ms(started)
                await self._send_json({"type": "tts", "state": "stop"})
                if speech_path is None:
                    speech_path = paths.reply_mp3
                    speech_path.write_bytes(b"")
                await self.repo.record_turn(
                    user_settings=self.user_settings,
                    device_id=self.device_id,
                    client_id=self.client_id,
                    session_id=self.session_id,
                    turn_id=paths.turn_id,
                    user_text=text,
                    reply_text=call_reply,
                    input_audio=paths.input_wav,
                    reply_audio=speech_path,
                    timings={
                        "stt_ms": stt_ms,
                        "agent_ms": 0,
                        "tts_ms": tts_total_ms,
                        "location_ms": 0,
                        "map_tool_ms": 0,
                        "llm_ttft_ms": 0,
                        "first_agent_delta_ms": 0,
                        "first_tts_audio_ms": tts_total_ms,
                    },
                )
                return

            agent_started = time.perf_counter()
            reply_parts: list[str] = []
            tts_started = 0.0
            tts_total_ms = 0
            first_agent_delta_ms: int | None = None
            first_tts_audio_ms: int | None = None
            llm_ttft_ms: int | None = None
            error_kind: str | None = None
            speech_path: Path | None = None
            sentence_buffer = ""
            sentence_index = 0
            allow_weak_punctuation = True

            await self._send_json({"type": "agent", "state": "thinking"})
            if self.agent is not None:
                self.agent.context.metadata.pop("llm_error_kind", None)
                self.agent.context.metadata.pop("map_tool_ms", None)
            location_started = time.perf_counter()
            await self._refresh_location_context(text)
            location_ms = _elapsed_ms(location_started)

            async for chunk in self.llm_pipeline.stream_agent_chunks(text):
                if not chunk:
                    continue
                if first_agent_delta_ms is None:
                    first_agent_delta_ms = _elapsed_ms(agent_started)
                    llm_ttft_ms = first_agent_delta_ms
                    pending_error = (
                        self.agent.context.metadata.get("llm_error_kind")
                        if self.agent is not None
                        else None
                    )
                    if pending_error:
                        error_kind = str(pending_error)
                        await self._send_json(
                            {
                                "type": "agent",
                                "state": "error",
                                "error_kind": error_kind,
                                "elapsed_ms": first_agent_delta_ms,
                            }
                        )
                reply_parts.append(chunk)
                await self._send_json(
                    {
                        "type": "agent",
                        "state": "delta",
                        "text": chunk,
                        "elapsed_ms": _elapsed_ms(agent_started),
                    }
                )
                sentence_buffer += chunk
                segments, sentence_buffer = self.tts_pipeline.pop_segments(
                    sentence_buffer,
                    allow_weak_punctuation=allow_weak_punctuation,
                )
                if segments:
                    allow_weak_punctuation = False
                for segment in segments:
                    if not tts_started:
                        tts_started = time.perf_counter()
                        await self._send_json({"type": "tts", "state": "start"})
                    sentence_index += 1
                    speech_path = await self.tts_pipeline.synthesize_and_send(
                        segment,
                        paths.reply_mp3,
                        sentence_index,
                        started,
                    )
                    tts_total_ms = _elapsed_ms(tts_started)
                    if first_tts_audio_ms is None:
                        first_tts_audio_ms = _elapsed_ms(started)

            segments, sentence_buffer = self.tts_pipeline.pop_segments(sentence_buffer, force=True)
            for segment in segments:
                if not tts_started:
                    tts_started = time.perf_counter()
                    await self._send_json({"type": "tts", "state": "start"})
                sentence_index += 1
                speech_path = await self.tts_pipeline.synthesize_and_send(
                    segment,
                    paths.reply_mp3,
                    sentence_index,
                    started,
                )
                tts_total_ms = _elapsed_ms(tts_started)
                if first_tts_audio_ms is None:
                    first_tts_audio_ms = _elapsed_ms(started)

            reply = "".join(reply_parts).strip()
            agent_ms = _elapsed_ms(agent_started)
            if not reply and not error_kind:
                error_kind = "empty_reply"
                await self._send_json(
                    {
                        "type": "agent",
                        "state": "error",
                        "error_kind": error_kind,
                        "elapsed_ms": agent_ms,
                    }
                )
                reply = Agent._get_fallback_response()
            await self._send_json(
                {"type": "agent", "state": "reply", "text": reply, "elapsed_ms": agent_ms}
            )

            if speech_path is None and reply:
                tts_started = time.perf_counter()
                await self._send_json({"type": "tts", "state": "start"})
                speech_path = await self.tts_pipeline.synthesize_and_send(
                    reply,
                    paths.reply_mp3,
                    1,
                    started,
                )
                tts_total_ms = _elapsed_ms(tts_started)
                first_tts_audio_ms = _elapsed_ms(started)
            if speech_path is None:
                speech_path = paths.reply_mp3
                speech_path.write_bytes(b"")
            map_tool_ms = (
                int(self.agent.context.metadata.get("map_tool_ms") or 0)
                if self.agent is not None
                else 0
            )
            await self.repo.record_turn(
                user_settings=self.user_settings,
                device_id=self.device_id,
                client_id=self.client_id,
                session_id=self.session_id,
                turn_id=paths.turn_id,
                user_text=text,
                reply_text=reply,
                input_audio=paths.input_wav,
                reply_audio=speech_path,
                timings={
                    "stt_ms": stt_ms,
                    "agent_ms": agent_ms,
                    "tts_ms": tts_total_ms,
                    "location_ms": location_ms,
                    "map_tool_ms": map_tool_ms,
                    "llm_ttft_ms": llm_ttft_ms or 0,
                    "first_agent_delta_ms": first_agent_delta_ms or 0,
                    "first_tts_audio_ms": first_tts_audio_ms or 0,
                    "total_elapsed_ms": _elapsed_ms(started),
                    "error_kind": error_kind or "",
                },
            )

            # 异步记录消费流水（不阻塞语音核心流）
            billing_svc = getattr(self.app.state, "billing", None) if self.app is not None else None
            if billing_svc is not None and self.user_settings is not None:
                stt_seconds = len(pcm) / 32000.0 if 'pcm' in locals() else 0.0
                stt_model = getattr(self.device.stt, "provider", "default") if self.device and self.device.stt else "default"

                # 估算 LLM Token
                input_tokens = int((2500 + len(text)) * 1.2)
                output_tokens = int(len(reply) * 1.3)
                llm_tokens = input_tokens + output_tokens
                llm_model = getattr(self.agent.config.llm, "model", "default") if self.agent else "default"

                tts_chars = len(reply)
                tts_model = getattr(self.agent_record, "voice_type", "volcengine-clone") if self.agent_record else "volcengine-clone"

                billing_svc.record_usage_in_background(
                    user_id=self.user_settings.user_id,
                    device_id=self.device_id,
                    stt_seconds=stt_seconds,
                    stt_model=stt_model,
                    llm_tokens=llm_tokens,
                    llm_model=llm_model,
                    tts_chars=tts_chars,
                    tts_model=tts_model
                )

            if (
                self.companion_id
                and self.user_id
                and hasattr(self.repo, "companions")
                and str(self.device_id or "").startswith("soft_")
            ):
                asyncio.create_task(
                    self.repo.companions.after_companion_turn(
                        user_id=self.user_id,
                        companion_id=self.companion_id,
                        voice_turn=True,
                    )
                )

            asyncio.create_task(self.repo.compress_if_needed(self.user_settings))
            if self.user_settings is not None:
                asyncio.create_task(
                    self.repo.maybe_merge_rolling_summary(
                        self.user_settings,
                        self.device,
                        force=False,
                    )
                )
            await self._send_json(
                {
                    "type": "tts",
                    "state": "stop",
                    "elapsed_ms": tts_total_ms,
                    "total_elapsed_ms": _elapsed_ms(started),
                    "first_agent_delta_ms": first_agent_delta_ms or 0,
                    "first_tts_audio_ms": first_tts_audio_ms or 0,
                    "llm_ttft_ms": llm_ttft_ms or 0,
                    "location_ms": location_ms,
                    "map_tool_ms": map_tool_ms,
                    "error_kind": error_kind or "",
                }
            )
        except Exception as exc:
            err_msg = str(exc)
            if (
                err_msg == QUOTA_EXHAUSTED_MESSAGE
                or "额度已用尽" in err_msg
                or "陪伴点已用尽" in err_msg
                or "quota" in err_msg.lower()
            ):
                await self._send_json({"type": "error", "error_kind": "quota_exhausted", "message": err_msg})
            else:
                await self._send_json({"type": "error", "message": err_msg})
        finally:
            self.audio_chunks = []

    async def _process_text_turn(self, text: str) -> None:
        """E2E/开发用：跳过 STT，直接以文本触发一轮 Agent（需 SHUXIN_VOICE_DEV_TEXT_TURN=1）。"""
        started = time.perf_counter()
        skip_tts = os.environ.get("SHUXIN_VOICE_E2E_SKIP_TTS") == "1"
        try:
            await self._assert_quota_for_turn()
            await self._ensure_runtime()
            assert self.audio_store is not None
            assert self.user_settings is not None
            assert self.agent is not None
            paths = self.audio_store.new_turn_paths(self.device_id, self.session_id or None)
            self.session_id = paths.session_id
            paths.input_wav.parent.mkdir(parents=True, exist_ok=True)
            paths.input_wav.write_bytes(b"")
            await self._send_json({"type": "stt", "state": "final", "text": text, "elapsed_ms": 0})

            agent_started = time.perf_counter()
            await self._send_json({"type": "agent", "state": "thinking"})
            if self.agent is not None:
                self.agent.context.metadata.pop("map_tool_ms", None)
            location_started = time.perf_counter()
            await self._refresh_location_context(text)
            location_ms = _elapsed_ms(location_started)
            loop = asyncio.get_event_loop()
            reply = await loop.run_in_executor(None, lambda: self.agent.chat(text).strip())
            agent_ms = _elapsed_ms(agent_started)
            await self._send_json(
                {"type": "agent", "state": "reply", "text": reply, "elapsed_ms": agent_ms}
            )

            tts_total_ms = 0
            speech_path = paths.reply_mp3
            if reply and not skip_tts:
                await self._send_json({"type": "tts", "state": "start"})
                tts_started = time.perf_counter()
                speech_path = await self.tts_pipeline.synthesize_and_send(
                    reply, paths.reply_mp3, 1, started
                )
                tts_total_ms = _elapsed_ms(tts_started)
            else:
                speech_path.parent.mkdir(parents=True, exist_ok=True)
                speech_path.write_bytes(b"")

            await self.repo.record_turn(
                user_settings=self.user_settings,
                device_id=self.device_id,
                client_id=self.client_id,
                session_id=self.session_id,
                turn_id=paths.turn_id,
                user_text=text,
                reply_text=reply,
                input_audio=paths.input_wav,
                reply_audio=speech_path,
                timings={
                    "stt_ms": 0,
                    "agent_ms": agent_ms,
                    "tts_ms": tts_total_ms,
                    "total_elapsed_ms": _elapsed_ms(started),
                },
            )

            # 异步记录消费流水（不阻塞语音核心流）
            billing_svc = getattr(self.app.state, "billing", None) if self.app is not None else None
            if billing_svc is not None and self.user_settings is not None:
                # 文本会话跳过 STT 计费
                stt_seconds = 0.0
                stt_model = "default"

                # 估算 LLM Token
                input_tokens = int((2500 + len(text)) * 1.2)
                output_tokens = int(len(reply) * 1.3)
                llm_tokens = input_tokens + output_tokens
                llm_model = getattr(self.agent.config.llm, "model", "default") if self.agent else "default"

                tts_chars = len(reply)
                tts_model = getattr(self.agent_record, "voice_type", "volcengine-clone") if self.agent_record else "volcengine-clone"

                billing_svc.record_usage_in_background(
                    user_id=self.user_settings.user_id,
                    device_id=self.device_id,
                    stt_seconds=stt_seconds,
                    stt_model=stt_model,
                    llm_tokens=llm_tokens,
                    llm_model=llm_model,
                    tts_chars=tts_chars,
                    tts_model=tts_model
                )

            asyncio.create_task(self.repo.compress_if_needed(self.user_settings))
            if self.user_settings is not None:
                asyncio.create_task(
                    self.repo.maybe_merge_rolling_summary(
                        self.user_settings,
                        self.device,
                        force=False,
                    )
                )
            await self._send_json(
                {
                    "type": "tts",
                    "state": "stop",
                    "elapsed_ms": tts_total_ms,
                    "total_elapsed_ms": _elapsed_ms(started),
                }
            )
        except Exception as exc:
            err_msg = str(exc)
            if (
                err_msg == QUOTA_EXHAUSTED_MESSAGE
                or "额度已用尽" in err_msg
                or "陪伴点已用尽" in err_msg
                or "quota" in err_msg.lower()
            ):
                await self._send_json({"type": "error", "error_kind": "quota_exhausted", "message": err_msg})
            else:
                await self._send_json({"type": "error", "message": err_msg})

    async def _assert_quota_for_turn(self) -> None:
        """每轮对话前检查用户级汇总额度（同一用户名下多设备共用）。"""
        if not self.device_id:
            return
        if hasattr(self.repo, "assert_device_quota_available"):
            await self.repo.assert_device_quota_available(self.device_id)
        elif self.user_id and hasattr(self.repo, "assert_user_quota_available"):
            await self.repo.assert_user_quota_available(self.user_id)

    async def _reset_runtime(self) -> None:
        """切换用户或设备时重建运行态，确保配置和记忆目录重新绑定。"""
        await self.shutdown(mark_offline=False)
        self.stt = None
        self.tts = None
        self.device = None
        self.agent_record = None

    async def _maybe_reveal_mbti_on_hello(self) -> None:
        """开箱或补播：sealed 时揭晓+TTS；小程序已揭晓时仅补播自我介绍。"""
        # 注意：只用局部变量 _device 读取元数据，不覆盖 self.device，
        # 避免把未经 merge_llm_device_config 的裸设备配置覆盖已合并的版本。
        _device = await self.repo.get_device(self.device_id)
        metadata = _device.metadata or {}

        if needs_mbti_reveal(metadata):
            result = await self.repo.try_reveal_and_lock(self.device_id, "first_hello")
            if result and result.get("is_first_reveal"):
                await self._play_mbti_intro(
                    result,
                    is_first_reveal=True,
                    bind_success_prefix=False,
                )
                await self.repo.mark_device_intro_played(self.device_id)
                if self.device is not None:
                    self.device.metadata["mbti_status"] = "locked"
                    self.device.metadata["device_intro_played"] = True
            return

        await self.play_pending_device_intro(bind_success_prefix=True)

    async def play_pending_device_intro(self, *, bind_success_prefix: bool = True) -> bool:
        """Play one-time device intro when MBTI is locked but TTS has not played."""
        if not self.device_id:
            return False
        async with vsr.intro_lock(self.device_id):
            # 同样只用局部变量读取元数据，不覆盖 self.device，
            # 避免把未经 merge_llm_device_config 的裸设备配置覆盖已合并的版本。
            _device = await self.repo.get_device(self.device_id)
            metadata = _device.metadata or {}
            if not needs_device_intro(metadata):
                return False
            mbti = str(metadata.get("mbti") or "").strip().upper()
            if not mbti:
                return False
            await self._play_mbti_intro(
                {"mbti": mbti},
                is_first_reveal=False,
                bind_success_prefix=bind_success_prefix,
            )
            await self.repo.mark_device_intro_played(self.device_id)
            if self.device is not None:
                self.device.metadata["device_intro_played"] = True
            return True

    async def _play_mbti_intro(
        self,
        payload: dict[str, Any],
        *,
        is_first_reveal: bool,
        bind_success_prefix: bool = False,
    ) -> None:
        mbti = str(payload.get("mbti") or "").strip().upper()
        if not mbti:
            return
        identity = IdentityEngine(mbti)
        tagline = identity.get_description()
        reveal = build_device_intro_text(mbti, bind_success_prefix=bind_success_prefix)

        if is_first_reveal:
            await self._send_json(
                {
                    "type": "mbti/reveal",
                    "mbti": mbti,
                    "tagline": tagline,
                    "is_first_reveal": True,
                }
            )
        await self._send_json(
            {"type": "agent", "state": "reply", "text": reveal, "elapsed_ms": 0}
        )
        try:
            await self._ensure_runtime()
            await self._play_proactive_tts(reveal)
        except Exception as exc:
            logger.warning("mbti intro TTS skipped: %s", exc)

    async def _play_proactive_tts(self, text: str) -> None:
        """播报无需 LLM 的固定台词（如开箱 reveal_script）。"""
        if os.environ.get("SHUXIN_VOICE_E2E_SKIP_TTS") == "1":
            return
        if self.tts is None or self.audio_store is None:
            return

        started = time.perf_counter()
        paths = self.audio_store.new_turn_paths(self.device_id, self.session_id or None)
        output_path = paths.reply_mp3.parent / f"mbti-reveal-{uuid.uuid4().hex[:8]}.mp3"
        tts_started = time.perf_counter()
        await self._send_json({"type": "tts", "state": "start"})
        await self.tts_pipeline.synthesize_and_send(text, output_path, 1, started)
        await self._send_json(
            {
                "type": "tts",
                "state": "stop",
                "elapsed_ms": _elapsed_ms(tts_started),
                "total_elapsed_ms": _elapsed_ms(started),
            }
        )



    def _is_web_demo_client(self) -> bool:
        cid = self.client_id or "web-demo"
        return cid in {"web-demo", "soft-miniprogram", "miniprogram"}

    def _uses_opus_downlink(self) -> bool:
        if self._is_web_demo_client():
            return False
        return self.audio_wire_format == "opus" or self.hardware_session

    async def _send_downlink_bytes(self, data: bytes) -> None:
        """Chunk downlink binary for hardware (default 2KB, hard cap 4KB per frame)."""
        if not data:
            return
        if self._is_web_demo_client():
            await self.websocket.send_bytes(data)
            return
        chunk_size = _ws_downlink_max_bytes()
        if len(data) > HARD_WS_DOWNLINK_MAX_BYTES:
            logger.warning(
                "downlink binary %d bytes exceeds %d; streaming in %d-byte chunks",
                len(data),
                HARD_WS_DOWNLINK_MAX_BYTES,
                chunk_size,
            )
        yield_seconds = _ws_downlink_yield_seconds()
        for offset in range(0, len(data), chunk_size):
            await self.websocket.send_bytes(data[offset : offset + chunk_size])
            if yield_seconds > 0:
                await asyncio.sleep(yield_seconds)

    async def _send_opus_downlink_stream(self, mp3_path: Path) -> None:
        """Send one Opus packet per WebSocket binary frame (streamed transcoding)."""
        max_bytes = _ws_downlink_max_bytes()
        packet_count = 0
        for packet in iter_transcode_mp3_to_opus_frames(
            mp3_path,
            sample_rate=int(self.audio_params["downlink_sample_rate"]),
            frame_duration_ms=int(self.audio_params["frame_duration"]),
        ):
            if looks_like_mp3(packet):
                logger.warning("downlink opus packet looks like mp3 header; skipping")
                continue
            if len(packet) > max_bytes:
                logger.warning(
                    "downlink opus packet %d bytes exceeds max %d",
                    len(packet),
                    max_bytes,
                )
            await self._send_downlink_bytes(packet)
            packet_count += 1
        if packet_count == 0:
            logger.warning("no opus packets produced for %s", mp3_path)



    async def _ensure_runtime(self) -> None:
        """懒加载设备配置、STT/TTS provider 和按用户隔离的 Agent。"""
        if self.agent is not None:
            return

        if self._agent_init_task is not None and asyncio.current_task() != self._agent_init_task:
            await self._agent_init_task
            return

        if self.audio_store is None:
            self.user_settings = await self.repo.authenticate_user(DEFAULT_USER_ID, "")
            self.user_id = self.user_settings.user_id
            self.audio_store = AudioFileStore(self.shuxin_home, self.out_dir, self.user_id)
            self.session_id = self.session_id or uuid.uuid4().hex
            await self.repo.ensure_session(
                session_id=self.session_id,
                user_id=self.user_id,
                device_id=self.device_id,
                client_id=self.client_id,
            )
        if self.device is None:
            self.device = await self.repo.get_device(self.device_id)
        self.device.llm = merge_llm_device_config(
            self.device.llm,
            default_platform_llm_config(),
        )
        if self.user_settings and self.user_settings.llm_config:
            self.device.llm = merge_llm_device_config(
                self.device.llm,
                self.user_settings.llm_config,
            )
        if not str(self.device.llm.api_key or "").strip():
            from shuxin.core.config import Config

            fallback = Config.load()
            if fallback.llm.api_key:
                self.device.llm = merge_llm_device_config(
                    self.device.llm,
                    {
                        "provider": fallback.llm.provider,
                        "model": fallback.llm.model,
                        "base_url": fallback.llm.base_url,
                        "api_key": fallback.llm.api_key,
                    },
                )
        if self.agent is None:
            if hasattr(self.repo, "assert_device_quota_available"):
                await self.repo.assert_device_quota_available(self.device_id)
            elif hasattr(self.repo, "assert_user_quota_available"):
                await self.repo.assert_user_quota_available(self.user_id)
            if not self.device.llm.api_key:
                raise ValueError("LLM api_key is not configured for this device/user")
            if is_tencent_realtime_stt(self.device.stt):
                self.stt = None
            else:
                self.stt = create_stt_provider(self.device.stt)
            agent_id = DEFAULT_AGENT_ID
            if self.user_settings and self.user_settings.agent_id.strip():
                agent_id = self.user_settings.agent_id.strip()
            elif hasattr(self.repo, "get_user_agent_id"):
                agent_id = await self.repo.get_user_agent_id(self.user_id)
            self.agent_record = await self.repo.get_agent(agent_id)
            self.tts = create_tts_provider_from_agent(self.agent_record)
            self.agent = self.service.create_agent(
                self.device,
                user_home=self.audio_store.user_shuxin_home(),
                agent=self.agent_record,
                companion_id=self.companion_id,
            )
            self.agent.context.metadata["channel"] = "voice"
            self.agent.context.metadata["agent_id"] = self.agent_record.agent_id
            self.agent.context.metadata["client_ip"] = self.client_ip
            self._setup_agent_tool_callbacks()
            await asyncio.to_thread(self.agent.initialize)
            VoiceService.apply_device_mbti(self.agent, self.device, self.agent_record)
            if self.companion_id and self.user_id and hasattr(self.repo, "companions"):
                try:
                    companion = await self.repo.companions.get_companion_for_user(
                        user_id=self.user_id,
                        companion_id=self.companion_id,
                    )
                    mbti = str(companion.get("mbti") or "").strip().upper()
                    if mbti:
                        self.agent.identity.set_mbti(mbti)
                        self.agent.context.metadata["companion_id"] = self.companion_id
                        self.agent.context.metadata["companion_mbti"] = mbti
                        await asyncio.to_thread(self.agent._build_system_prompt)
                except Exception as exc:
                    logger.warning("apply companion_id failed: %s", exc)

    def _setup_agent_tool_callbacks(self) -> None:
        if self.agent is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        def on_tool_round_start(reason: str) -> None:
            asyncio.run_coroutine_threadsafe(
                self._send_json(
                    {"type": "agent", "state": "thinking", "reason": reason}
                ),
                loop,
            )

        self.agent.tool_loop_callbacks = ToolLoopCallbacks(
            on_tool_round_start=on_tool_round_start,
        )

    async def _refresh_location_context(self, user_text: str = "") -> None:
        """按需解析位置：非地图意图不查 IP；同会话内复用缓存。"""
        if self.agent is None:
            return

        if not may_need_location(user_text):
            self.agent.context.metadata.pop("location_context", None)
            self.agent.context.metadata.pop("location_ctx", None)
            self.agent.context.metadata.pop("location_debug", None)
            return

        provider = get_location_provider(self.agent.config.map)
        user_home = None
        if self.audio_store is not None:
            user_home = self.audio_store.user_shuxin_home()

        effective_ip = resolve_effective_ip(self.client_ip) or ""
        now = time.time()
        ttl = _location_cache_ttl_seconds()
        cached = self._location_cache
        if (
            cached
            and cached.get("effective_ip") == effective_ip
            and (now - float(cached.get("cached_at") or 0)) < ttl
        ):
            hit_payload = dict(cached)
            hit_debug = dict(hit_payload.get("debug") or {})
            hit_debug["cache"] = "hit"
            hit_payload["debug"] = hit_debug
            self._apply_location_cache_to_agent(hit_payload)
            logger.debug("location_context cache hit: %s", hit_debug)
            return

        def resolve():
            ctx = provider.resolve_location_context(
                ip=effective_ip or None,
                user_home=user_home,
            )
            return ctx, format_location_context_block(ctx)

        ctx, block = await asyncio.to_thread(resolve)
        debug = {
            "client_ip": self.client_ip,
            "effective_ip": effective_ip,
            "source": ctx.source,
            "confidence": ctx.confidence,
            "label": ctx.label,
            "city": ctx.city,
            "district": ctx.district,
            "city_adcode": ctx.city_adcode,
            "lat": ctx.lat,
            "lng": ctx.lng,
            "cache": "miss",
        }
        self._location_cache = {
            "ctx": ctx,
            "block": block,
            "effective_ip": effective_ip,
            "cached_at": now,
            "debug": debug,
        }
        self._apply_location_cache_to_agent(self._location_cache)
        logger.info("location_context resolved: %s", debug)

    def _apply_location_cache_to_agent(self, cached: dict) -> None:
        """把会话缓存的位置写入 Agent metadata。"""
        if self.agent is None:
            return
        ctx = cached.get("ctx")
        block = str(cached.get("block") or "")
        debug = dict(cached.get("debug") or {})
        self.agent.context.metadata["location_debug"] = debug
        if ctx is not None and getattr(ctx, "label", ""):
            self.agent.context.metadata["location_ctx"] = ctx.to_metadata_dict()
        else:
            self.agent.context.metadata.pop("location_ctx", None)
        if block.strip():
            self.agent.context.metadata["location_context"] = block
        else:
            self.agent.context.metadata.pop("location_context", None)

    async def _send_json(self, data: dict) -> bool:
        """以 UTF-8 JSON 文本消息下发状态，保留中文错误和回复内容。

        对已关闭/失效的 WebSocket 吞掉异常并从在线登记表移除，避免 call/ring
        等广播路径触发 ASGI ``websocket.send`` after ``websocket.close``。
        返回 True 表示发送成功。
        """
        try:
            await self.websocket.send_text(json.dumps(data, ensure_ascii=False))
            return True
        except Exception as exc:
            msg_type = data.get("type") if isinstance(data, dict) else None
            logger.warning(
                "websocket send failed device_id=%s type=%s: %s",
                self.device_id,
                msg_type,
                exc,
            )
            if self.device_id:
                vsr.unregister(self.device_id, self)
            return False



def _elapsed_ms(started: float) -> int:
    """把 perf_counter 起点转换为毫秒耗时，便于前端展示链路耗时。"""
    return int((time.perf_counter() - started) * 1000)


