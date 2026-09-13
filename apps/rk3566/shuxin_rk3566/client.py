"""RK3566 WebSocket 语音客户端：兼容现有 ESP32 云端协议。"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from shuxin_rk3566.actions import extract_actions
from shuxin_rk3566.chassis import MotionController
from shuxin_rk3566.config import DeviceRuntimeConfig
from shuxin_rk3566.motion_intent import MotionCommand, parse_motion_intent

logger = logging.getLogger("shuxin.rk3566.client")

ActionHandler = Callable[[str, str], None]


@dataclass
class TurnResult:
    stt_text: str = ""
    agent_reply: str = ""
    error_kind: str = ""
    factory_acceptance: bool = False
    actions: list[str] = field(default_factory=list)
    downlink_packets: list[bytes] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    motion: MotionCommand | None = None


class Rk3566VoiceClient:
    """Speaks hello / listen / ping / factory_verify_ack against /ws/voice."""

    def __init__(
        self,
        config: DeviceRuntimeConfig,
        *,
        on_action: ActionHandler | None = None,
        motion: MotionController | None = None,
    ) -> None:
        self.config = config
        self.on_action = on_action
        self._motion = motion
        self._ws = None
        self._ping_task: asyncio.Task[None] | None = None
        self.session: dict[str, Any] = {}

    async def connect(self) -> dict[str, Any]:
        try:
            import websockets
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("websockets is required (apps/rk3566/requirements.txt)") from exc

        if not self.config.device_secret:
            raise RuntimeError("device_secret is empty; set SHUXIN_DEVICE_SECRET")

        logger.info("connecting %s", self.config.ws_url)
        self._ws = await websockets.connect(
            self.config.ws_url,
            open_timeout=10,
            close_timeout=5,
            max_size=2**22,
        )
        ready = json.loads(await asyncio.wait_for(self._ws.recv(), timeout=self.config.recv_timeout_seconds))
        logger.info("server ready: %s", ready)

        hello = {
            "type": "hello",
            "device_code": self.config.device_code,
            "device_secret": self.config.device_secret,
            "client_id": self.config.client_id,
            "audio_params": {
                "format": "opus",
                "sample_rate": self.config.uplink_sample_rate,
                "channels": self.config.channels,
                "frame_duration": self.config.frame_duration_ms,
            },
        }
        await self._ws.send(json.dumps(hello, ensure_ascii=False))
        hello_ok = json.loads(await asyncio.wait_for(self._ws.recv(), timeout=self.config.recv_timeout_seconds))
        if hello_ok.get("type") == "error" or hello_ok.get("state") != "ok":
            raise RuntimeError(f"hello failed: {hello_ok}")
        audio = hello_ok.get("audio_params") or {}
        if audio.get("format") != "opus":
            raise RuntimeError(f"server did not negotiate opus: {hello_ok}")
        self.session = hello_ok
        logger.info(
            "hello ok device=%s user=%s factory=%s",
            hello_ok.get("device_id"),
            hello_ok.get("user_id"),
            bool(hello_ok.get("factory_acceptance")),
        )
        self._ping_task = asyncio.create_task(self._ping_loop(), name="rk3566-ping")
        return hello_ok

    async def close(self) -> None:
        if self._ping_task is not None:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass
            self._ping_task = None
        if self._motion is not None:
            await self._motion.close()
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def _ping_loop(self) -> None:
        assert self._ws is not None
        while True:
            await asyncio.sleep(self.config.ping_interval_seconds)
            try:
                await self._ws.send(json.dumps({"type": "ping"}))
            except Exception:
                logger.debug("ping failed", exc_info=True)
                return

    async def _send_json(self, payload: dict[str, Any]) -> None:
        assert self._ws is not None
        await self._ws.send(json.dumps(payload, ensure_ascii=False))

    async def abort(self) -> None:
        await self._send_json({"type": "abort"})

    def _emit_actions(self, raw_text: str) -> list[str]:
        actions = extract_actions(raw_text)
        for action in actions:
            logger.info("action: %s", action)
            if self.on_action is not None:
                self.on_action(action, raw_text)
        return actions

    async def _maybe_drive(self, text: str, turn: TurnResult) -> None:
        command = parse_motion_intent(text)
        if command is None:
            return
        if turn.motion is not None and not command.is_stop and turn.motion.action == command.action:
            return
        turn.motion = command
        logger.info(
            "voice motion %s duration=%.2fs speed=%.2f text=%s",
            command.action,
            command.duration_s,
            command.speed,
            command.source_text,
        )
        if self._motion is not None:
            await self._motion.handle(command)

    async def _handle_control(self, data: dict[str, Any], turn: TurnResult) -> None:
        msg_type = str(data.get("type") or "")
        if msg_type == "factory_verify":
            verify_id = str(data.get("verify_id") or "")
            logger.info("factory_verify id=%s", verify_id)
            await self._send_json(
                {"type": "factory_verify_ack", "verify_id": verify_id, "status": "ok"}
            )
            return
        if msg_type == "factory_verify_fail":
            logger.warning("factory_verify_fail reason=%s", data.get("reason"))
            return
        if msg_type == "mbti/reveal":
            logger.info("mbti reveal %s %s", data.get("mbti"), data.get("tagline"))
            return
        if msg_type == "error":
            kind = str(data.get("error_kind") or data.get("message") or "error")
            turn.error_kind = kind
            logger.error("server error: %s", data)
            return

        text = str(data.get("text") or "")
        state = str(data.get("state") or "")
        if msg_type == "stt" and state in {"final", "sentence_final"}:
            cleaned = text.strip()
            if state == "final" or not turn.stt_text:
                turn.stt_text = cleaned
            await self._maybe_drive(cleaned, turn)
        elif msg_type == "agent" and state == "reply":
            turn.agent_reply = text.strip()
        elif msg_type == "agent" and state == "error":
            turn.error_kind = str(data.get("error_kind") or "llm_error")
        elif msg_type == "tts" and state in {"sentence_start", "sentence_stop"}:
            turn.actions.extend(self._emit_actions(text))

    async def converse(self, uplink_packets: Iterable[bytes]) -> TurnResult:
        """One listen turn: send Opus frames, wait until tts/stop (or error)."""
        if self._ws is None:
            raise RuntimeError("not connected")
        if self.session.get("factory_acceptance"):
            raise RuntimeError("factory acceptance session cannot listen; bind the device first")

        turn = TurnResult(factory_acceptance=bool(self.session.get("factory_acceptance")))
        await self._send_json({"type": "listen", "state": "start"})
        in_sentence = False
        for packet in uplink_packets:
            if packet:
                await self._ws.send(packet)
        await self._send_json({"type": "listen", "state": "stop"})

        while True:
            try:
                message = await asyncio.wait_for(self._ws.recv(), timeout=self.config.recv_timeout_seconds)
            except asyncio.TimeoutError as exc:
                raise RuntimeError("timed out waiting for voice pipeline") from exc

            if isinstance(message, bytes):
                if in_sentence:
                    turn.downlink_packets.append(message)
                continue

            data = json.loads(message)
            turn.events.append({k: data.get(k) for k in ("type", "state", "error_kind") if k in data})
            await self._handle_control(data, turn)
            msg_type = str(data.get("type") or "")
            state = str(data.get("state") or "")
            if msg_type == "tts" and state == "sentence_start":
                in_sentence = True
            elif msg_type == "tts" and state == "sentence_stop":
                in_sentence = False
            elif msg_type == "tts" and state == "stop":
                break
            elif msg_type == "error" and turn.error_kind in {"quota_exhausted", "invalid device secret"}:
                break
        return turn

    async def __aenter__(self) -> Rk3566VoiceClient:
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()
