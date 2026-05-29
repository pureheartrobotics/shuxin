from __future__ import annotations

import argparse
import asyncio
import json
import os
import threading
import uuid
import time
from pathlib import Path

from shuxin.core.config import get_shuxin_home
from shuxin.voice.adapters import VoiceAdapterRegistry
from shuxin.voice.audio_files import AudioFileStore
from shuxin.voice.barcode import decode_barcode_image_base64, generate_code128_png
from shuxin.voice.config import DeviceConfigProvider, LLMDeviceConfig, merge_llm_device_config
from shuxin.voice.db import PostgresDatabase
from shuxin.voice.local_repository import VoiceLocalRepository
from shuxin.voice.postgres_repository import VoicePostgresRepository
from shuxin.voice.providers import create_stt_provider, create_tts_provider
from shuxin.voice.service import VoiceService
from shuxin.voice.tencent_realtime_asr import (
    TencentRealtimeASRResult,
    TencentRealtimeASRSession,
    is_tencent_realtime_stt,
)
from shuxin.voice.users import DEFAULT_USER_ID, UserConfigProvider

# WebSocket 上行音频统一按 16kHz / mono / PCM16 处理。
# 浏览器测试台和后续硬件只需要发送裸 PCM 帧，不需要封装 wav 头。
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
CHANNELS = 1
SENTENCE_DELIMITERS = "。！？!?；;\n"
FIRST_SEGMENT_WEAK_DELIMITERS = "，,、"
MAX_STREAMING_TTS_CHARS = 48


def _pop_speakable_segments(
    buffer: str,
    *,
    force: bool = False,
    allow_weak_punctuation: bool = False,
) -> tuple[list[str], str]:
    """Split streamed LLM text into speakable segments for low-latency TTS."""
    delimiters = SENTENCE_DELIMITERS
    if allow_weak_punctuation:
        delimiters += FIRST_SEGMENT_WEAK_DELIMITERS
    segments: list[str] = []
    while buffer:
        cut_at = -1
        for index, char in enumerate(buffer):
            if char in delimiters:
                cut_at = index + 1
                break
        if cut_at < 0 and force:
            cut_at = len(buffer)
        if cut_at < 0 and len(buffer) >= MAX_STREAMING_TTS_CHARS:
            cut_at = MAX_STREAMING_TTS_CHARS
        if cut_at < 0:
            break
        segment = buffer[:cut_at].strip()
        buffer = buffer[cut_at:]
        if segment:
            segments.append(segment)
    return segments, buffer


def build_parser() -> argparse.ArgumentParser:
    """构建 voice server 的命令行参数。

    这个入口主要给 Docker 常驻服务和本机无硬件测试使用。
    """
    parser = argparse.ArgumentParser(description="ShuXin voice WebSocket demo server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--device-config", default=None)
    parser.add_argument("--users-config", default=None)
    parser.add_argument("--default-device-id", default="demo-device-001")
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/web"))
    return parser


def create_app(
    device_config: str | None = None,
    users_config: str | None = None,
    default_device_id: str = "demo-device-001",
    out_dir: Path = Path("outputs/web"),
):
    """创建 FastAPI 应用，并注册语音测试台相关 HTTP/WebSocket 入口。

    主要职责:
    1. 暴露浏览器测试页和健康检查接口。
    2. 提供用户语音状态/摘要查询接口。
    3. 通过 `/ws/voice` 承接准实时语音对话。
    """
    try:
        from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
        from fastapi.responses import HTMLResponse, JSONResponse, Response
    except ImportError as exc:
        raise RuntimeError(
            "FastAPI is not installed. Add voice web dependencies and rebuild Docker."
        ) from exc
    globals()["Request"] = Request
    globals()["WebSocket"] = WebSocket

    app = FastAPI(title="ShuXin Voice Demo")
    device_provider = DeviceConfigProvider(device_config)
    user_provider = UserConfigProvider(users_config)
    service = VoiceService(device_provider)
    shuxin_home = get_shuxin_home()
    out_dir.mkdir(parents=True, exist_ok=True)
    database_url = os.environ.get("DATABASE_URL", "")
    db = PostgresDatabase(
        database_url,
        min_size=int(os.environ.get("SHUXIN_DB_POOL_MIN", "1")),
        max_size=int(os.environ.get("SHUXIN_DB_POOL_MAX", "10")),
    )
    adapter_registry = VoiceAdapterRegistry(shuxin_home=shuxin_home)
    admin_token = os.environ.get("SHUXIN_ADMIN_TOKEN", "")

    @app.on_event("startup")
    async def startup() -> None:
        if database_url:
            await db.connect()
            await db.migrate()
            app.state.repo = VoicePostgresRepository(db.pool)
            await app.state.repo.seed_from_yaml(
                device_config_path=device_config or os.environ.get("VOICE_DEVICE_CONFIG"),
                users_config_path=users_config or os.environ.get("SHUXIN_USERS_CONFIG"),
                default_device_id=default_device_id,
            )
        else:
            app.state.repo = VoiceLocalRepository(
                device_provider=device_provider,
                user_provider=user_provider,
                shuxin_home=shuxin_home,
                out_dir=out_dir,
            )

    @app.on_event("shutdown")
    async def shutdown() -> None:
        if database_url:
            await db.close()

    def repo():
        value = getattr(app.state, "repo", None)
        if value is None:
            raise RuntimeError("voice repository is not initialized")
        return value

    def require_admin(request: Request) -> None:
        provided = request.headers.get("X-Admin-Token") or request.cookies.get("shuxin_admin")
        if not admin_token:
            raise PermissionError("SHUXIN_ADMIN_TOKEN is required for admin access")
        if provided != admin_token:
            raise PermissionError("invalid admin token")

    @app.get("/health")
    async def health():
        return JSONResponse(
            {
                "status": "ok",
                "service": "shuxin-voice-demo",
                "storage": "postgres" if database_url else "yaml-fallback",
            }
        )

    @app.post("/api/barcodes/decode")
    async def decode_barcode(request: Request):
        try:
            payload = await request.json()
            return JSONResponse(
                decode_barcode_image_base64(str(payload.get("image_base64") or ""))
            )
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/api/wechat/login")
    async def wechat_login(request: Request):
        try:
            payload = await request.json()
            return JSONResponse(
                await repo().create_wechat_session(wx_code=str(payload.get("wx_code") or ""))
            )
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/api/factory/devices/provision")
    async def factory_provision_device(request: Request):
        try:
            require_admin(request)
            payload = await request.json()
            return JSONResponse(await repo().provision_device(str(payload.get("device_code") or "")))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/admin/api/factory/devices/batch")
    async def admin_factory_provision_batch(request: Request):
        try:
            require_admin(request)
            payload = await request.json()
            return JSONResponse(await repo().provision_devices_batch(payload))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/admin/api/factory/devices/next-sequence")
    async def admin_factory_next_sequence(request: Request, device_prefix: str = "SX"):
        try:
            require_admin(request)
            return JSONResponse(await repo().next_device_sequence(device_prefix))
        except PermissionError as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/admin/api/claim-codes/{claim_code}/barcode.png")
    async def admin_claim_code_barcode(request: Request, claim_code: str):
        try:
            require_admin(request)
            return Response(content=generate_code128_png(claim_code), media_type="image/png")
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/api/devices/bind")
    async def bind_device(request: Request):
        try:
            payload = await request.json()
            return JSONResponse(
                await repo().bind_device(
                    wx_code=str(payload.get("wx_code") or ""),
                    session_token=str(payload.get("session_token") or ""),
                    claim_code=str(payload.get("claim_code") or ""),
                    device_code=str(payload.get("device_code") or ""),
                )
            )
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/api/devices/unbind")
    async def unbind_device(request: Request):
        try:
            payload = await request.json()
            session_token = str(payload.get("session_token") or "")
            if session_token:
                return JSONResponse(
                    await repo().unbind_device_by_session(
                        session_token=session_token,
                        device_code=str(payload.get("device_code") or ""),
                    )
                )
            wx_code = str(payload.get("wx_code") or "")
            if wx_code:
                return JSONResponse(
                    await repo().unbind_device_by_wx_code(
                        wx_code=wx_code,
                        device_code=str(payload.get("device_code") or ""),
                    )
                )
            return JSONResponse(
                await repo().unbind_device(
                    user_id=str(payload.get("user_id") or ""),
                    device_code=str(payload.get("device_code") or ""),
                )
            )
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/api/devices/my")
    async def my_devices(request: Request):
        try:
            payload = await request.json()
            return JSONResponse(
                await repo().list_my_devices(
                    wx_code=str(payload.get("wx_code") or ""),
                    session_token=str(payload.get("session_token") or ""),
                )
            )
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/voice-demo")
    async def voice_demo():
        return HTMLResponse(_web_demo_html(default_device_id))

    @app.get("/voice/status")
    async def voice_status(request: Request, user_id: str = DEFAULT_USER_ID, token: str = ""):
        try:
            require_admin(request)
            settings = await repo().authenticate_user(user_id, token)
            return JSONResponse(await repo().status(settings))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)

    @app.get("/voice/export")
    async def voice_export(request: Request, user_id: str = DEFAULT_USER_ID, token: str = ""):
        try:
            require_admin(request)
            settings = await repo().authenticate_user(user_id, token)
            return JSONResponse(
                {
                    "user_id": settings.user_id,
                    "shared_memory": await repo().export_summary(settings),
                    "include_audio": False,
                }
            )
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)

    @app.get("/admin")
    async def admin_page(request: Request):
        authenticated = False
        try:
            require_admin(request)
            authenticated = True
        except Exception:
            authenticated = False
        return HTMLResponse(_admin_html(authenticated))

    @app.post("/admin/api/login")
    async def admin_login(request: Request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if not admin_token:
            return JSONResponse({"error": "SHUXIN_ADMIN_TOKEN is required"}, status_code=500)
        if payload.get("token") != admin_token:
            return JSONResponse({"error": "invalid admin token"}, status_code=403)
        response = JSONResponse({"ok": True})
        response.set_cookie(
            "shuxin_admin",
            admin_token,
            httponly=True,
            samesite="strict",
            secure=False,
        )
        return response

    @app.get("/admin/api/devices")
    async def admin_list_devices(request: Request, limit: int = 50, cursor: str = "", q: str = ""):
        try:
            require_admin(request)
            return JSONResponse(await repo().list_devices(limit=limit, cursor=cursor, q=q))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)

    @app.post("/admin/api/devices")
    async def admin_upsert_device(request: Request):
        try:
            require_admin(request)
            payload = await request.json()
            return JSONResponse(await repo().upsert_device(payload))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.patch("/admin/api/devices/{device_id}")
    async def admin_update_device_label(request: Request, device_id: str):
        try:
            require_admin(request)
            payload = await request.json()
            return JSONResponse(await repo().update_device_label(device_id, payload))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.delete("/admin/api/devices/{device_id}")
    async def admin_delete_device(request: Request, device_id: str):
        try:
            require_admin(request)
            await repo().soft_delete_device(device_id)
            return JSONResponse({"ok": True})
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/admin/api/devices/{device_id}/rotate-secret")
    async def admin_rotate_device_secret(request: Request, device_id: str):
        try:
            require_admin(request)
            return JSONResponse(await repo().rotate_device_secret(device_id))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/admin/api/devices/{device_id}/reset-claim")
    async def admin_reset_claim_code(request: Request, device_id: str):
        try:
            require_admin(request)
            return JSONResponse(await repo().reset_claim_code(device_id))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/admin/api/users")
    async def admin_list_users(request: Request, limit: int = 50, cursor: str = "", q: str = ""):
        try:
            require_admin(request)
            return JSONResponse(await repo().list_users(limit=limit, cursor=cursor, q=q))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)

    @app.post("/admin/api/users")
    async def admin_upsert_user(request: Request):
        try:
            require_admin(request)
            payload = await request.json()
            return JSONResponse(await repo().upsert_user(payload))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.delete("/admin/api/users/{user_id}")
    async def admin_delete_user(request: Request, user_id: str):
        try:
            require_admin(request)
            await repo().soft_delete_user(user_id)
            return JSONResponse({"ok": True})
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/admin/api/bindings")
    async def admin_list_bindings(request: Request, limit: int = 50, cursor: str = "", q: str = ""):
        try:
            require_admin(request)
            return JSONResponse(await repo().list_bindings(limit=limit, cursor=cursor, q=q))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)

    @app.post("/admin/api/bindings")
    async def admin_bind_device(request: Request):
        try:
            require_admin(request)
            payload = await request.json()
            return JSONResponse(
                await repo().admin_bind_device(
                    user_id=str(payload.get("user_id") or ""),
                    device_id=str(payload.get("device_id") or payload.get("device_code") or ""),
                )
            )
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/admin/api/bindings/unbind")
    async def admin_unbind_device(request: Request):
        try:
            require_admin(request)
            payload = await request.json()
            return JSONResponse(
                await repo().admin_unbind_device(binding_id=str(payload.get("binding_id") or ""))
            )
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/admin/api/adapters")
    async def admin_adapters(request: Request):
        try:
            require_admin(request)
            return JSONResponse({"items": adapter_registry.list_adapters()})
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)

    @app.post("/admin/api/adapters/{adapter_name}/{action}")
    async def admin_call_adapter(request: Request, adapter_name: str, action: str):
        try:
            require_admin(request)
            payload = await request.json()
            result = adapter_registry.call(adapter_name, action, payload)
            await repo().record_adapter_action(
                adapter_name=adapter_name,
                action=action,
                request_json=payload,
                result_json=result,
            )
            return JSONResponse({"result": result})
        except Exception as exc:
            try:
                await repo().record_adapter_action(
                    adapter_name=adapter_name,
                    action=action,
                    request_json={},
                    error=str(exc),
                )
            except Exception:
                pass
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.websocket("/ws/voice")
    async def voice_ws(websocket: WebSocket):
        await websocket.accept()
        session = _VoiceWebSocketSession(
            websocket=websocket,
            service=service,
            repo=repo(),
            shuxin_home=shuxin_home,
            default_device_id=default_device_id,
            out_dir=out_dir,
        )
        try:
            await session.run()
        except WebSocketDisconnect:
            await session.shutdown()

    return app


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
    ):
        self.websocket = websocket
        self.service = service
        self.repo = repo
        self.shuxin_home = shuxin_home
        self.default_device_id = default_device_id
        self.out_dir = out_dir
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
        self.audio_chunks: list[bytes] = []
        self.realtime_asr: TencentRealtimeASRSession | None = None
        self.realtime_stt_started = 0.0
        self.listening = False

    async def run(self) -> None:
        """进入消息循环，按文本控制消息和二进制音频帧分流处理。"""
        await self._send_json(
            {"type": "hello", "state": "ready", "device_id": self.device_id}
        )

        while True:
            message = await self.websocket.receive()
            if "text" in message:
                await self._handle_text(message["text"])
            elif "bytes" in message:
                await self._handle_audio_frame(message["bytes"])

    async def shutdown(self, mark_offline: bool = True) -> None:
        """关闭连接时释放当前 Agent，避免插件状态和资源泄漏。"""
        if self.realtime_asr is not None:
            await self.realtime_asr.close()
            self.realtime_asr = None
        if self.agent is not None:
            await asyncio.to_thread(self.agent.shutdown)
            self.agent = None
        if mark_offline and self.device_id:
            try:
                await self.repo.touch_device_status(device_id=self.device_id, online=False)
            except Exception:
                pass

    async def _handle_text(self, raw: str) -> None:
        """处理设备/浏览器上行的 JSON 控制消息。

        `hello` 决定用户身份和设备配置；`listen start/stop` 决定一轮
        语音采集边界；`abort` 清空当前轮缓存；`ping` 用于连接保活。
        """
        data = json.loads(raw)
        message_type = data.get("type")

        if message_type == "hello":
            try:
                if data.get("device_code") or data.get("device_secret"):
                    self.user_settings = await self.repo.authenticate_device(
                        data.get("device_code") or data.get("device_id") or self.default_device_id,
                        data.get("device_secret") or "",
                    )
                else:
                    self.user_settings = await self.repo.authenticate_user(
                        data.get("user_id") or DEFAULT_USER_ID,
                        data.get("token") or "",
                    )
            except Exception as exc:
                await self._send_json({"type": "error", "message": str(exc)})
                return
            self.user_id = self.user_settings.user_id
            self.device_id = (
                data.get("device_code")
                or data.get("device_id")
                or self.default_device_id
            )
            self.client_id = data.get("client_id") or "web-demo"
            self.audio_store = AudioFileStore(self.shuxin_home, self.out_dir, self.user_id)
            self.session_id = data.get("session_id") or uuid.uuid4().hex
            await self.repo.ensure_session(
                session_id=self.session_id,
                user_id=self.user_id,
                device_id=self.device_id,
                client_id=self.client_id,
            )
            await self.repo.touch_device_status(
                device_id=self.device_id,
                online=True,
                session_id=self.session_id,
            )
            await self._reset_runtime()
            await self._send_json(
                {
                    "type": "hello",
                    "state": "ok",
                    "user_id": self.user_id,
                    "device_id": self.device_id,
                    "client_id": self.client_id,
                    "session_id": self.session_id,
                }
            )
            return

        if message_type == "listen" and data.get("state") == "start":
            self.audio_chunks = []
            self.listening = True
            try:
                await self._start_realtime_asr_if_needed()
            except Exception as exc:
                self.listening = False
                await self._send_json({"type": "error", "message": str(exc)})
                return
            await self._send_json({"type": "listen", "state": "start"})
            return

        if message_type == "listen" and data.get("state") == "stop":
            self.listening = False
            await self._process_turn()
            return

        if message_type == "abort":
            self.audio_chunks = []
            self.listening = False
            if self.realtime_asr is not None:
                await self.realtime_asr.close()
                self.realtime_asr = None
            await self._send_json({"type": "abort", "state": "ok"})
            return

        if message_type == "ping":
            await self._send_json({"type": "pong", "ts": time.time()})
            return

        await self._send_json({"type": "error", "message": f"unsupported message: {data}"})

    async def _handle_audio_frame(self, frame: bytes) -> None:
        """缓存 listen 窗口内收到的 PCM16 二进制音频帧，并按需转发实时 ASR。"""
        if self.listening and frame:
            self.audio_chunks.append(frame)
            if self.realtime_asr is not None:
                await self.realtime_asr.send_audio(frame)

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
            await self._ensure_runtime()
            assert self.audio_store is not None
            assert self.user_settings is not None
            paths = self.audio_store.new_turn_paths(self.device_id, self.session_id or None)
            self.session_id = paths.session_id
            self.audio_store.write_input_wav(pcm, paths.input_wav)
            await self._send_json({"type": "stt", "state": "start"})
            stt_started = time.perf_counter()
            if self.realtime_asr is not None:
                try:
                    text = await self.realtime_asr.finish()
                finally:
                    self.realtime_asr = None
            else:
                text = await self.stt.transcribe(paths.input_wav)
            stt_ms = _elapsed_ms(stt_started)
            await self._send_json(
                {"type": "stt", "state": "final", "text": text, "elapsed_ms": stt_ms}
            )

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

            async for chunk in self._stream_agent_chunks(text):
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
                segments, sentence_buffer = _pop_speakable_segments(
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
                    speech_path = await self._synthesize_and_send_sentence(
                        segment,
                        paths.reply_mp3,
                        sentence_index,
                        started,
                    )
                    tts_total_ms = _elapsed_ms(tts_started)
                    if first_tts_audio_ms is None:
                        first_tts_audio_ms = _elapsed_ms(started)

            segments, sentence_buffer = _pop_speakable_segments(sentence_buffer, force=True)
            for segment in segments:
                if not tts_started:
                    tts_started = time.perf_counter()
                    await self._send_json({"type": "tts", "state": "start"})
                sentence_index += 1
                speech_path = await self._synthesize_and_send_sentence(
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
            await self._send_json(
                {"type": "agent", "state": "reply", "text": reply, "elapsed_ms": agent_ms}
            )

            if speech_path is None and reply:
                tts_started = time.perf_counter()
                await self._send_json({"type": "tts", "state": "start"})
                speech_path = await self._synthesize_and_send_sentence(
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
                    "llm_ttft_ms": llm_ttft_ms or 0,
                    "first_agent_delta_ms": first_agent_delta_ms or 0,
                    "first_tts_audio_ms": first_tts_audio_ms or 0,
                    "total_elapsed_ms": _elapsed_ms(started),
                    "error_kind": error_kind or "",
                },
            )
            asyncio.create_task(self.repo.compress_if_needed(self.user_settings))
            await self._send_json(
                {
                    "type": "tts",
                    "state": "stop",
                    "elapsed_ms": tts_total_ms,
                    "total_elapsed_ms": _elapsed_ms(started),
                    "first_agent_delta_ms": first_agent_delta_ms or 0,
                    "first_tts_audio_ms": first_tts_audio_ms or 0,
                    "llm_ttft_ms": llm_ttft_ms or 0,
                    "error_kind": error_kind or "",
                }
            )
        except Exception as exc:
            await self._send_json({"type": "error", "message": str(exc)})
        finally:
            self.audio_chunks = []

    async def _reset_runtime(self) -> None:
        """切换用户或设备时重建运行态，确保配置和记忆目录重新绑定。"""
        await self.shutdown(mark_offline=False)
        self.stt = None
        self.tts = None
        self.device = None

    async def _stream_agent_chunks(self, text: str):
        """Run the sync Agent streaming iterator without blocking the event loop."""
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        done = object()

        def worker() -> None:
            try:
                for chunk in self.agent.chat_stream(text):
                    loop.call_soon_threadsafe(queue.put_nowait, chunk)
            except Exception as exc:
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, done)

        threading.Thread(target=worker, daemon=True).start()
        while True:
            item = await queue.get()
            if item is done:
                break
            if isinstance(item, Exception):
                raise item
            yield str(item)

    async def _synthesize_and_send_sentence(
        self,
        text: str,
        base_path: Path,
        sentence_index: int,
        turn_started: float,
    ) -> Path:
        """Synthesize one sentence and send its audio immediately."""
        if sentence_index == 1:
            output_path = base_path
        else:
            output_path = base_path.with_name(
                f"{base_path.stem}-{sentence_index:03d}{base_path.suffix}"
            )
        await self._send_json(
            {
                "type": "tts",
                "state": "sentence_start",
                "text": text,
                "index": sentence_index,
                "total_elapsed_ms": _elapsed_ms(turn_started),
            }
        )
        sentence_started = time.perf_counter()
        speech_path = await self.tts.synthesize(text, output_path)
        await self.websocket.send_bytes(speech_path.read_bytes())
        await self._send_json(
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

    async def _start_realtime_asr_if_needed(self) -> None:
        """在录音开始时启动腾讯云实时 ASR，让识别和录音并行。"""
        await self._ensure_runtime()
        if self.device is None or not is_tencent_realtime_stt(self.device.stt):
            return
        if self.realtime_asr is not None:
            await self.realtime_asr.close()
        self.realtime_stt_started = time.perf_counter()
        self.realtime_asr = TencentRealtimeASRSession(
            self.device.stt,
            on_result=self._handle_realtime_asr_result,
        )
        await self.realtime_asr.start()
        await self._send_json({"type": "stt", "state": "stream_start"})

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
        await self._send_json(
            {
                "type": "stt",
                "state": state,
                "text": result.text,
                "elapsed_ms": _elapsed_ms(self.realtime_stt_started),
            }
        )

    async def _ensure_runtime(self) -> None:
        """懒加载设备配置、STT/TTS provider 和按用户隔离的 Agent。"""
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
            if self.user_settings and self.user_settings.llm_config:
                self.device.llm = merge_llm_device_config(
                    self.device.llm,
                    self.user_settings.llm_config,
                )
            if not self.device.llm.api_key:
                raise ValueError("LLM api_key is not configured for this device/user")
            if is_tencent_realtime_stt(self.device.stt):
                self.stt = None
            else:
                self.stt = create_stt_provider(self.device.stt)
            self.tts = create_tts_provider(self.device.tts)
            self.agent = self.service.create_agent(
                self.device,
                user_home=self.audio_store.user_shuxin_home(),
            )
            self.agent.context.metadata["channel"] = "voice"
            await asyncio.to_thread(self.agent.initialize)

    async def _send_json(self, data: dict) -> None:
        """以 UTF-8 JSON 文本消息下发状态，保留中文错误和回复内容。"""
        await self.websocket.send_text(json.dumps(data, ensure_ascii=False))


def _elapsed_ms(started: float) -> int:
    """把 perf_counter 起点转换为毫秒耗时，便于前端展示链路耗时。"""
    return int((time.perf_counter() - started) * 1000)


def _admin_html(authenticated: bool) -> str:
    """返回轻量后台页面；所有数据操作仍走 /admin/api。"""
    auth_state = "true" if authenticated else "false"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ShuXin 管理后台</title>
  <style>
    body {{ margin: 0; font-family: "Trebuchet MS", "Segoe UI", sans-serif; color: #1e2524; background: #edf0ec; }}
    header {{ height: 60px; display: flex; align-items: center; justify-content: space-between; padding: 0 24px; border-bottom: 1px solid #d8ddd5; background: #fbfaf5; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 22px; }}
    h1 {{ font-size: 20px; margin: 0; }}
    h2 {{ font-size: 16px; margin: 0 0 12px; }}
    input, textarea, select {{ box-sizing: border-box; width: 100%; border: 1px solid #cbd4ca; border-radius: 6px; padding: 9px 10px; font: inherit; background: white; }}
    textarea {{ min-height: 130px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }}
    button {{ height: 36px; border: 0; border-radius: 6px; padding: 0 12px; color: white; background: #245849; cursor: pointer; }}
    button:disabled {{ cursor: not-allowed; opacity: .55; }}
    button.secondary {{ color: #20242a; background: #dfe5dc; }}
    button.danger {{ background: #b8453f; }}
    .grid {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, 420px); gap: 16px; align-items: start; }}
    .stack {{ display: grid; gap: 16px; }}
    .panel {{ background: #fffef9; border: 1px solid #d8ddd5; border-radius: 8px; padding: 16px; box-shadow: 0 12px 34px rgba(55, 70, 58, .06); }}
    .toolbar {{ display: flex; gap: 8px; align-items: center; margin-bottom: 12px; }}
    .toolbar input {{ min-width: 220px; }}
    .toolbar select {{ width: 86px; }}
    .pager {{ display: flex; gap: 8px; align-items: center; justify-content: flex-end; margin-top: 12px; }}
    .page-size {{ width: 86px; }}
    .form-row {{ display: grid; grid-template-columns: repeat(6, minmax(110px, 1fr)); gap: 8px; align-items: end; }}
    .form-row.compact {{ grid-template-columns: repeat(5, minmax(130px, 1fr)); }}
    .table {{ display: grid; gap: 6px; overflow-x: auto; }}
    .table-row {{ display: grid; grid-template-columns: 140px 170px 90px 1fr 430px; gap: 8px; align-items: center; min-width: 960px; padding: 8px 0; border-bottom: 1px solid #eef1f4; }}
    .table-row.users {{ grid-template-columns: 130px 90px 100px 120px 120px 150px 1fr 150px 330px; min-width: 1330px; }}
    .table-head {{ color: #647083; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
    .login {{ max-width: 420px; margin: 80px auto 0; }}
    .list {{ display: grid; gap: 8px; }}
    .item {{ display: grid; grid-template-columns: 1fr auto; gap: 12px; align-items: center; padding: 10px 0; border-bottom: 1px solid #eef1f4; }}
    .item.selectable {{ padding: 12px; border: 1px solid #e3e7df; border-radius: 8px; background: #ffffff; cursor: pointer; }}
    .item.selectable:hover {{ border-color: #93aa9b; }}
    .item.selected {{ border-color: #245849; background: #eef6f0; }}
    .item.muted {{ opacity: .62; }}
    .meta {{ color: #647083; font-size: 13px; margin-top: 3px; }}
    .badge {{ display: inline-flex; align-items: center; height: 22px; padding: 0 8px; border-radius: 999px; font-size: 12px; color: #245849; background: #e2eee7; }}
    .badge.warn {{ color: #8a4a18; background: #f4e4ce; }}
    .badge.off {{ color: #6b7280; background: #eceff1; }}
    .tabs {{ display: flex; gap: 8px; margin-bottom: 16px; }}
    .tabs button.active {{ background: #1e2524; }}
    .bind-board {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(240px, 300px) minmax(0, 1fr); gap: 14px; align-items: start; }}
    .bind-action {{ display: grid; gap: 10px; }}
    .bind-summary {{ min-height: 120px; padding: 12px; border: 1px dashed #b9c5ba; border-radius: 8px; background: #f7f8f3; }}
    .hint {{ color: #647083; font-size: 13px; line-height: 1.5; }}
    pre {{ white-space: pre-wrap; margin: 0; font-size: 13px; }}
  </style>
</head>
<body>
  <header><h1>ShuXin 管理后台</h1><button class="secondary" onclick="loadAll()">刷新</button></header>
  <main>
    <section id="login" class="panel login">
      <h2>管理员登录</h2>
      <div class="toolbar"><input id="adminToken" type="password" placeholder="SHUXIN_ADMIN_TOKEN" /><button onclick="login()">登录</button></div>
      <pre id="loginMsg"></pre>
    </section>
    <section id="admin" style="display:none">
      <div class="tabs">
        <button id="tabDevices" class="active" onclick="showTab('devices')">设备</button>
        <button id="tabUsers" onclick="showTab('users')">用户</button>
        <button id="tabBindings" onclick="showTab('bindings')">绑定</button>
        <button id="tabAdapters" onclick="showTab('adapters')">适配器</button>
      </div>
      <div id="devices" class="stack">
        <div class="panel">
          <h2>批量制码</h2>
          <div class="form-row">
            <label><span class="hint">设备前缀</span><input id="batchDevicePrefix" value="SX" onchange="refreshBatchStart()" /></label>
            <label><span class="hint">起始编号</span><input id="batchStart" type="number" value="1" min="1" /></label>
            <label><span class="hint">外壳码前缀</span><input id="batchLabelPrefix" value="CLM" /></label>
            <label><span class="hint">批次</span><input id="batchLabelBatch" value="A001" /></label>
            <label><span class="hint">数量</span><input id="batchQuantity" type="number" value="3" min="1" max="500" /></label>
            <button onclick="provisionBatch()">生成并入库</button>
          </div>
          <div class="toolbar" style="margin-top:12px"><button class="secondary" onclick="downloadBatchCsv()">下载本批 CSV</button><span id="batchNextHint" class="hint">device_secret 只在本次生成结果里明文显示。</span></div>
          <div id="batchResult" class="table"></div>
        </div>
        <div class="panel">
          <div class="toolbar" style="justify-content:space-between">
            <h2>设备状态与配置</h2>
            <div class="toolbar" style="margin-bottom:0">
              <input id="devicesSearch" placeholder="查找设备 / 外壳码 / 备注" />
              <select id="devicesLimit" class="page-size"><option value="20">20</option><option value="50">50</option></select>
              <button class="secondary" onclick="resetList('devices')">查找</button>
            </div>
          </div>
          <div id="deviceList" class="table"></div>
          <div id="devicesPager" class="pager"></div>
        </div>
      </div>
      <div id="users" class="stack" style="display:none">
        <div class="panel">
          <h2>新增用户与模型配置</h2>
          <div class="form-row compact">
            <label><span class="hint">用户 ID</span><input id="newUserId" value="demo-user" /></label>
            <label><span class="hint">Token 额度</span><input id="newTokenQuota" type="number" value="0" min="0" /></label>
            <label><span class="hint">模型</span><input id="newModel" placeholder="deepseek-chat" /></label>
            <label><span class="hint">Base URL</span><input id="newBaseUrl" placeholder="https://api.deepseek.com" /></label>
            <label><span class="hint">API Key</span><input id="newApiKey" type="password" placeholder="只保存，不回显" /></label>
          </div>
          <div class="toolbar" style="margin-top:12px"><button onclick="createUser()">保存用户</button></div>
        </div>
        <div class="panel">
          <div class="toolbar" style="justify-content:space-between">
            <h2>用户与额度</h2>
            <div class="toolbar" style="margin-bottom:0">
              <input id="usersSearch" placeholder="查找用户 / 模型 / Base URL" />
              <select id="usersLimit" class="page-size"><option value="20">20</option><option value="50">50</option></select>
              <button class="secondary" onclick="resetList('users')">查找</button>
            </div>
          </div>
          <div id="userList" class="table"></div>
          <div id="usersPager" class="pager"></div>
        </div>
      </div>
      <div id="bindings" class="grid" style="display:none">
        <div class="panel" style="grid-column:1 / -1">
          <div class="toolbar" style="justify-content:space-between">
            <h2>点击式用户设备绑定</h2>
            <button class="secondary" onclick="loadAll()">刷新列表</button>
          </div>
          <div class="bind-board">
            <section>
              <h2>选择用户</h2>
              <div id="bindUserList" class="list"></div>
            </section>
            <section class="bind-action">
              <h2>绑定操作</h2>
              <div id="bindSummary" class="bind-summary hint">先选择一个用户，再选择一台未绑定设备。</div>
              <button id="bindSelectedBtn" onclick="bindSelected()" disabled>绑定所选</button>
              <div class="hint">用户 token 仅用于旧 demo 兼容；小程序和真实硬件使用微信 openid 与设备绑定关系。</div>
            </section>
            <section>
              <h2>选择设备</h2>
              <div id="bindDeviceList" class="list"></div>
            </section>
          </div>
        </div>
        <div class="panel">
          <div class="toolbar" style="justify-content:space-between">
            <h2>当前绑定</h2>
            <div class="toolbar" style="margin-bottom:0">
              <input id="bindingsSearch" placeholder="查找用户 / 设备 / 绑定 ID" />
              <select id="bindingsLimit" class="page-size"><option value="20">20</option><option value="50">50</option></select>
              <button class="secondary" onclick="resetList('bindings')">查找</button>
            </div>
          </div>
          <div id="bindingList" class="list"></div>
          <div id="bindingsPager" class="pager"></div>
        </div>
        <div class="panel"><h2>说明</h2><div class="hint">后台只给管理端使用。删除用户或设备是软删除；解绑只解除设备访问权，不删除用户记忆。</div><pre id="bindingMsg"></pre></div>
      </div>
      <div id="adapters" class="grid" style="display:none">
        <div class="panel"><h2>可用适配器</h2><div id="adapterList" class="list"></div></div>
        <div class="panel"><h2>调用适配器</h2><textarea id="adapterPayload"></textarea><div class="toolbar"><button onclick="callAdapter()">调用</button></div><pre id="adapterResult"></pre></div>
      </div>
    </section>
  </main>
  <script>
    let authenticated = {auth_state};
    let users = [];
    let devices = [];
    let bindings = [];
    let lastBatch = [];
    let selectedUserId = '';
    let selectedDeviceId = '';
    const listState = {{
      devices: {{cursor:'', nextCursor:'', stack:[], q:'', limit:20}},
      users: {{cursor:'', nextCursor:'', stack:[], q:'', limit:20}},
      bindings: {{cursor:'', nextCursor:'', stack:[], q:'', limit:20}},
    }};
    const headers = () => ({{'Content-Type': 'application/json'}});
    function $(id) {{ return document.getElementById(id); }}
    function esc(value) {{
      return String(value ?? '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
    }}
    function boot() {{
      $('login').style.display = authenticated ? 'none' : 'block';
      $('admin').style.display = authenticated ? 'block' : 'none';
      $('adapterPayload').value = JSON.stringify({{adapter_name:'skills', action:'list', params:{{}}}}, null, 2);
      if (authenticated) {{ refreshBatchStart(); loadAll(); }}
    }}
    async function login() {{
      const res = await fetch('/admin/api/login', {{method:'POST', headers:headers(), body:JSON.stringify({{token:$('adminToken').value}})}});
      const data = await res.json();
      if (!res.ok) {{ $('loginMsg').textContent = data.error || 'login failed'; return; }}
      authenticated = true; boot();
    }}
    function showTab(name) {{
      for (const id of ['devices','users','bindings','adapters']) $(''+id).style.display = id === name ? 'grid' : 'none';
      for (const id of ['tabDevices','tabUsers','tabBindings','tabAdapters']) $(id).classList.remove('active');
      $('tab' + name[0].toUpperCase() + name.slice(1)).classList.add('active');
    }}
    function listUrl(name, path) {{
      const state = listState[name];
      const params = new URLSearchParams({{limit:String(state.limit), cursor:state.cursor, q:state.q}});
      return `${{path}}?${{params.toString()}}`;
    }}
    function syncListControls(name) {{
      const state = listState[name];
      const search = $(name + 'Search');
      const limit = $(name + 'Limit');
      if (search) state.q = search.value.trim();
      if (limit) state.limit = Number(limit.value || 20);
    }}
    function resetList(name) {{
      syncListControls(name);
      listState[name].cursor = '';
      listState[name].nextCursor = '';
      listState[name].stack = [];
      return loadList(name);
    }}
    function nextList(name) {{
      const state = listState[name];
      if (!state.nextCursor) return;
      state.stack.push(state.cursor);
      state.cursor = state.nextCursor;
      return loadList(name);
    }}
    function prevList(name) {{
      const state = listState[name];
      state.cursor = state.stack.pop() || '';
      return loadList(name);
    }}
    function loadList(name) {{
      if (name === 'devices') return loadDevices();
      if (name === 'users') return loadUsers();
      return loadBindings();
    }}
    function renderPager(name, count) {{
      const state = listState[name];
      const pager = $(name + 'Pager');
      if (!pager) return;
      pager.innerHTML = `
        <span class="hint">本页 ${{count}} 条 · 每页 ${{state.limit}} · ${{state.q ? `搜索: ${{esc(state.q)}}` : '未筛选'}}</span>
        <button class="secondary" onclick="prevList('${{name}}')" ${{state.stack.length ? '' : 'disabled'}}>上一页</button>
        <button class="secondary" onclick="nextList('${{name}}')" ${{state.nextCursor ? '' : 'disabled'}}>下一页</button>`;
    }}
    async function loadAll() {{ await Promise.all([loadDevices(), loadUsers(), loadBindings(), loadAdapters()]); }}
    async function loadDevices() {{
      const data = await (await fetch(listUrl('devices', '/admin/api/devices'))).json();
      devices = data.items || [];
      listState.devices.nextCursor = data.next_cursor || '';
      $('deviceList').innerHTML = `<div class="table-row table-head"><div>设备 ID</div><div>外壳码</div><div>状态</div><div>备注</div><div>操作</div></div>` + devices.map(d => `<div class="table-row">
        <div><strong>${{esc(d.device_id)}}</strong><div class="meta">auth=${{esc(d.auth_mode || '')}} secret=${{d.device_secret_configured ? '已配置' : '未配置'}}</div></div>
        <input id="claim_${{esc(d.device_id)}}" value="${{esc(d.claim_code || '')}}" />
        <div><span class="badge ${{d.status.online ? '' : 'off'}}">${{d.status.online ? '在线' : '离线'}}</span><div class="meta">${{esc(d.claim_status || '')}}</div></div>
        <input id="note_${{esc(d.device_id)}}" value="${{esc(d.note || '')}}" />
        <div class="toolbar">
          <button class="secondary" onclick="saveDeviceRow('${{esc(d.device_id)}}')">更新</button>
          <button class="secondary" onclick="resetClaim('${{esc(d.device_id)}}')">重置认领</button>
          <button class="secondary" onclick="rotateDeviceSecret('${{esc(d.device_id)}}')">换密钥</button>
          <button class="danger" onclick="deleteDevice('${{esc(d.device_id)}}')">删除</button>
        </div>
      </div>`).join('');
      renderPager('devices', devices.length);
      renderBindingBoard();
    }}
    async function loadUsers() {{
      const data = await (await fetch(listUrl('users', '/admin/api/users'))).json();
      users = data.items || [];
      listState.users.nextCursor = data.next_cursor || '';
      $('userList').innerHTML = `<div class="table-row users table-head"><div>用户</div><div>启用</div><div>音频MB</div><div>Token额度</div><div>已用</div><div>模型</div><div>Base URL</div><div>API Key</div><div>操作</div></div>` + users.map(u => {{
        const llm = u.llm_config || {{}};
        return `<div class="table-row users">
          <div><strong>${{esc(u.user_id)}}</strong><div class="meta">token=${{u.token_configured ? '已配置' : '未配置'}}</div></div>
          <input id="userEnabled_${{esc(u.user_id)}}" value="${{u.enabled ? 'true' : 'false'}}" />
          <input id="audio_${{esc(u.user_id)}}" type="number" min="1" value="${{u.audio_quota_mb || 512}}" />
          <input id="quota_${{esc(u.user_id)}}" type="number" min="0" value="${{u.token_quota_total || 0}}" />
          <input id="used_${{esc(u.user_id)}}" type="number" min="0" value="${{u.token_quota_used || 0}}" />
          <input id="model_${{esc(u.user_id)}}" value="${{esc(llm.model || '')}}" />
          <input id="base_${{esc(u.user_id)}}" value="${{esc(llm.base_url || '')}}" />
          <input id="apiKey_${{esc(u.user_id)}}" type="password" placeholder="${{llm.api_key ? '已配置' : '未配置'}}" />
          <div class="toolbar">
            <button class="secondary" onclick="saveUserRow('${{esc(u.user_id)}}')">更新</button>
            <button class="danger" onclick="deleteUser('${{esc(u.user_id)}}')">删除</button>
          </div>
        </div>`;
      }}).join('');
      renderPager('users', users.length);
      renderBindingBoard();
    }}
    async function loadBindings() {{
      const data = await (await fetch(listUrl('bindings', '/admin/api/bindings'))).json();
      bindings = data.items || [];
      listState.bindings.nextCursor = data.next_cursor || '';
      $('bindingList').innerHTML = bindings.length ? bindings.map(b => `<div class="item"><div><strong>${{esc(b.user_id)}}</strong><div class="meta">${{esc(b.device_id)}} online=${{b.online}} bound_at=${{esc(b.bound_at || '')}}</div></div><button class="danger" onclick="unbindBinding('${{esc(b.binding_id)}}')">解绑</button></div>`).join('') : '<div class="hint">暂无 active binding</div>';
      renderPager('bindings', bindings.length);
      renderBindingBoard();
    }}
    async function loadAdapters() {{
      const data = await (await fetch('/admin/api/adapters')).json();
      $('adapterList').innerHTML = (data.items || []).map(a => `<div class="item"><div><strong>${{a.name}}</strong><div class="meta">${{a.actions.join(', ')}}</div></div></div>`).join('');
    }}
    function activeBindingForDevice(deviceId) {{
      return bindings.find(b => b.device_id === deviceId && b.status === 'active');
    }}
    function renderBindingBoard() {{
      if (!$('bindUserList') || !$('bindDeviceList')) return;
      $('bindUserList').innerHTML = users.length ? users.map(u => `
        <div class="item selectable ${{selectedUserId === u.user_id ? 'selected' : ''}}" onclick="selectUser('${{esc(u.user_id)}}')">
          <div>
            <strong>${{esc(u.user_id)}}</strong>
            <div class="meta">音频 ${{u.audio_quota_mb}}MB · token ${{u.token_quota_used || 0}}/${{u.token_quota_total || 0}} · ${{u.enabled ? '启用' : '停用'}}</div>
          </div>
          <span class="badge">${{bindings.filter(b => b.user_id === u.user_id && b.status === 'active').length}} 台</span>
        </div>`).join('') : '<div class="hint">暂无用户</div>';
      $('bindDeviceList').innerHTML = devices.length ? devices.map(d => {{
        const binding = activeBindingForDevice(d.device_id);
        const disabled = Boolean(binding);
        const statusClass = d.status.online ? 'badge' : 'badge off';
        return `
          <div class="item selectable ${{selectedDeviceId === d.device_id ? 'selected' : ''}} ${{disabled ? 'muted' : ''}}" onclick="${{disabled ? '' : `selectDevice('${{esc(d.device_id)}}')`}}">
            <div>
              <strong>${{esc(d.device_id)}}</strong>
              <div class="meta">${{binding ? `已绑定 ${{esc(binding.user_id)}}` : '未绑定'}} · ${{esc(d.note || '')}}</div>
            </div>
            <span class="${{statusClass}}">${{d.status.online ? '在线' : '离线'}}</span>
          </div>`;
      }}).join('') : '<div class="hint">暂无设备</div>';
      const userLabel = selectedUserId || '未选择用户';
      const deviceLabel = selectedDeviceId || '未选择设备';
      $('bindSummary').textContent = `${{userLabel}} -> ${{deviceLabel}}`;
      $('bindSelectedBtn').disabled = !(selectedUserId && selectedDeviceId);
    }}
    function selectUser(userId) {{
      selectedUserId = userId;
      renderBindingBoard();
    }}
    function selectDevice(deviceId) {{
      selectedDeviceId = deviceId;
      renderBindingBoard();
    }}
    async function bindSelected() {{
      if (!(selectedUserId && selectedDeviceId)) return;
      const res = await fetch('/admin/api/bindings', {{
        method:'POST',
        headers:headers(),
        body:JSON.stringify({{user_id:selectedUserId, device_id:selectedDeviceId}})
      }});
      const data = await res.json();
      $('bindingMsg').textContent = JSON.stringify(data, null, 2);
      if (res.ok && !data.error) selectedDeviceId = '';
      await Promise.all([loadBindings(), loadDevices()]);
    }}
    function renderBatch(items) {{
      lastBatch = items || [];
      $('batchResult').innerHTML = lastBatch.length ? `<div class="table-row table-head"><div>设备 ID</div><div>外壳码</div><div>密钥</div><div>条码</div><div>扫码内容</div></div>` + lastBatch.map(item => `<div class="table-row">
        <div><strong>${{esc(item.device_id)}}</strong></div>
        <div>${{esc(item.claim_code)}}</div>
        <input value="${{esc(item.device_secret)}}" readonly />
        <div><img src="${{esc(item.barcode_url)}}" alt="${{esc(item.claim_code)}}" style="height:48px;background:white;border:1px solid #d8ddd5" /></div>
        <div class="meta">${{esc(item.qr_payload || '')}}</div>
      </div>`).join('') : '';
    }}
    async function refreshBatchStart() {{
      const prefix = $('batchDevicePrefix').value || 'SX';
      const params = new URLSearchParams({{device_prefix: prefix}});
      const res = await fetch('/admin/api/factory/devices/next-sequence?' + params.toString());
      const data = await res.json();
      if (!res.ok || data.error) {{ $('batchNextHint').textContent = data.error || '无法读取下一编号'; return; }}
      $('batchStart').value = data.next_sequence || 1;
      $('batchNextHint').textContent = `下一设备号 ${{data.next_device_id}}；device_secret 只在本次生成结果里明文显示。`;
    }}
    async function provisionBatch() {{
      const payload = {{
        device_prefix: $('batchDevicePrefix').value,
        device_start: Number($('batchStart').value || 1),
        label_prefix: $('batchLabelPrefix').value,
        label_batch: $('batchLabelBatch').value,
        quantity: Number($('batchQuantity').value || 1),
      }};
      const res = await fetch('/admin/api/factory/devices/batch', {{method:'POST', headers:headers(), body:JSON.stringify(payload)}});
      const data = await res.json();
      if (!res.ok || data.error) {{ alert(data.error || 'batch failed'); return; }}
      renderBatch(data.items || []);
      await refreshBatchStart();
      await loadDevices();
    }}
    function downloadBatchCsv() {{
      if (!lastBatch.length) return;
      const rows = [['device_id','claim_code','device_secret','qr_payload'], ...lastBatch.map(i => [i.device_id, i.claim_code, i.device_secret, i.qr_payload])];
      const csv = rows.map(row => row.map(cell => `"${{String(cell || '').replaceAll('"', '""')}}"`).join(',')).join('\\n');
      const blob = new Blob([csv], {{type:'text/csv;charset=utf-8'}});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'shuxin-device-batch.csv';
      a.click();
      URL.revokeObjectURL(url);
    }}
    async function saveDeviceRow(id) {{
      const payload = {{claim_code:$('claim_' + id).value, note:$('note_' + id).value, enabled:true}};
      const res = await fetch('/admin/api/devices/' + encodeURIComponent(id), {{method:'PATCH', headers:headers(), body:JSON.stringify(payload)}});
      const data = await res.json();
      if (!res.ok || data.error) alert(data.error || 'update failed');
      await loadDevices();
    }}
    async function resetClaim(id) {{
      const res = await fetch('/admin/api/devices/' + encodeURIComponent(id) + '/reset-claim', {{method:'POST', headers:headers()}});
      const data = await res.json();
      if (!res.ok || data.error) alert(data.error || 'reset failed');
      await loadDevices();
    }}
    async function createUser() {{
      const llm = {{model:$('newModel').value, base_url:$('newBaseUrl').value, api_key:$('newApiKey').value}};
      const payload = {{user_id:$('newUserId').value, token_quota_total:Number($('newTokenQuota').value || 0), token_quota_used:0, audio_quota_mb:512, enabled:true, llm_config:llm}};
      const res = await fetch('/admin/api/users', {{method:'POST', headers:headers(), body:JSON.stringify(payload)}});
      const data = await res.json();
      if (!res.ok || data.error) alert(data.error || 'save failed');
      $('newApiKey').value = '';
      await loadUsers();
    }}
    async function saveUserRow(id) {{
      const payload = {{
        user_id:id,
        token_quota_total:Number($('quota_' + id).value || 0),
        token_quota_used:Number($('used_' + id).value || 0),
        audio_quota_mb:Number($('audio_' + id).value || 512),
        enabled:$('userEnabled_' + id).value !== 'false',
        llm_config:{{model:$('model_' + id).value, base_url:$('base_' + id).value, api_key:$('apiKey_' + id).value}}
      }};
      const res = await fetch('/admin/api/users', {{method:'POST', headers:headers(), body:JSON.stringify(payload)}});
      const data = await res.json();
      if (!res.ok || data.error) alert(data.error || 'save failed');
      await loadUsers();
    }}
    async function rotateDeviceSecret(id) {{
      const res = await fetch('/admin/api/devices/' + encodeURIComponent(id) + '/rotate-secret', {{method:'POST', headers:headers()}});
      alert(JSON.stringify(await res.json(), null, 2));
      await loadDevices();
    }}
    async function unbindBinding(bindingId) {{
      const res = await fetch('/admin/api/bindings/unbind', {{method:'POST', headers:headers(), body:JSON.stringify({{binding_id: bindingId}})}});
      $('bindingMsg').textContent = JSON.stringify(await res.json(), null, 2);
      await Promise.all([loadBindings(), loadDevices()]);
    }}
    async function deleteDevice(id) {{ await fetch('/admin/api/devices/' + encodeURIComponent(id), {{method:'DELETE'}}); await loadDevices(); }}
    async function deleteUser(id) {{ await fetch('/admin/api/users/' + encodeURIComponent(id), {{method:'DELETE'}}); await loadUsers(); }}
    async function callAdapter() {{
      const body = JSON.parse($('adapterPayload').value);
      const res = await fetch(`/admin/api/adapters/${{body.adapter_name}}/${{body.action}}`, {{method:'POST', headers:headers(), body:JSON.stringify(body.params || {{}})}});
      $('adapterResult').textContent = JSON.stringify(await res.json(), null, 2);
    }}
    boot();
  </script>
</body>
</html>"""


def _web_demo_html(default_device_id: str) -> str:
    """返回内嵌浏览器测试台 HTML。

    测试台模拟未来硬件: 按住录音、Web Audio 下采样到 16k PCM16、
    WebSocket 上行音频帧，并播放服务端返回的 mp3。
    """
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ShuXin Voice Demo</title>
  <style>
    body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; background: #f6f7f9; color: #20242a; }}
    main {{ max-width: 880px; margin: 0 auto; padding: 28px 18px 40px; }}
    h1 {{ font-size: 28px; margin: 0 0 18px; }}
    .toolbar {{ display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-bottom: 18px; }}
    input {{ height: 38px; padding: 0 10px; border: 1px solid #cfd6df; border-radius: 6px; min-width: 220px; }}
    button {{ height: 40px; padding: 0 16px; border: 0; border-radius: 6px; background: #1b6ef3; color: white; cursor: pointer; }}
    button:disabled {{ background: #9aa7b6; cursor: not-allowed; }}
    #record {{ background: #d63847; min-width: 160px; }}
    #record.recording {{ background: #9f1d2b; }}
    .panel {{ background: white; border: 1px solid #e1e6ec; border-radius: 8px; padding: 16px; margin-top: 12px; }}
    .row {{ display: grid; grid-template-columns: 120px 1fr; gap: 12px; padding: 7px 0; border-bottom: 1px solid #eef1f4; }}
    .row:last-child {{ border-bottom: 0; }}
    .label {{ color: #657080; }}
    #log {{ white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; max-height: 280px; overflow: auto; }}
  </style>
</head>
<body>
  <main>
    <h1>ShuXin 语音测试台</h1>
    <div class="toolbar">
      <input id="deviceCode" value="{default_device_id}" aria-label="device code" />
      <input id="deviceSecret" value="dev-device-secret" aria-label="device secret" placeholder="device secret" />
      <input id="clientId" value="web-demo" aria-label="client id" />
      <button id="connect">连接</button>
      <button id="record" disabled>按住说话</button>
    </div>
    <div class="panel">
      <div class="row"><div class="label">连接状态</div><div id="status">未连接</div></div>
      <div class="row"><div class="label">绑定用户</div><div id="boundUser">-</div></div>
      <div class="row"><div class="label">识别文本</div><div id="stt">-</div></div>
      <div class="row"><div class="label">舒心回复</div><div id="reply">-</div></div>
      <div class="row"><div class="label">耗时</div><div id="timing">-</div></div>
    </div>
    <div class="panel"><div id="log"></div></div>
  </main>
  <script>
    const statusEl = document.getElementById('status');
    const sttEl = document.getElementById('stt');
    const replyEl = document.getElementById('reply');
    const timingEl = document.getElementById('timing');
    const boundUserEl = document.getElementById('boundUser');
    const logEl = document.getElementById('log');
    const connectBtn = document.getElementById('connect');
    const recordBtn = document.getElementById('record');
    const deviceInput = document.getElementById('deviceCode');
    const secretInput = document.getElementById('deviceSecret');
    const clientInput = document.getElementById('clientId');
    let ws, audioContext, source, processor, stream;
    let recording = false;
    let recordingRequested = false;
    let startingRecording = false;
    let audioQueue = [];
    let audioPlaying = false;

    function log(line) {{
      logEl.textContent += `${{new Date().toLocaleTimeString()}} ${{line}}\\n`;
      logEl.scrollTop = logEl.scrollHeight;
    }}

    function wsUrl() {{
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      return `${{protocol}}//${{location.host}}/ws/voice`;
    }}

    function enqueueAudio(data) {{
      audioQueue.push(data);
      playNextAudio();
    }}

    function playNextAudio() {{
      if (audioPlaying || !audioQueue.length) return;
      audioPlaying = true;
      const blob = new Blob([audioQueue.shift()], {{type: 'audio/mpeg'}});
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.onended = audio.onerror = () => {{
        URL.revokeObjectURL(url);
        audioPlaying = false;
        playNextAudio();
      }};
      audio.play().catch(() => {{
        URL.revokeObjectURL(url);
        audioPlaying = false;
        playNextAudio();
      }});
    }}

    connectBtn.onclick = () => {{
      if (recording || startingRecording) return;
      if (ws && ws.readyState === WebSocket.OPEN) ws.close();
      ws = new WebSocket(wsUrl());
      ws.binaryType = 'arraybuffer';
      connectBtn.disabled = true;
      statusEl.textContent = '连接中';
      ws.onopen = () => {{
        statusEl.textContent = '已连接';
        recordBtn.disabled = false;
        connectBtn.disabled = false;
        ws.send(JSON.stringify({{
          type: 'hello',
          device_code: deviceInput.value,
          device_secret: secretInput.value,
          client_id: clientInput.value || 'web-demo'
        }}));
      }};
      ws.onclose = () => {{
        statusEl.textContent = '已断开';
        recordBtn.disabled = true;
        connectBtn.disabled = false;
      }};
      ws.onerror = () => {{
        log('WebSocket error');
        connectBtn.disabled = false;
      }};
      ws.onmessage = (event) => {{
        if (typeof event.data !== 'string') {{
          enqueueAudio(event.data);
          return;
        }}
        const msg = JSON.parse(event.data);
        log(JSON.stringify(msg));
        if (msg.type === 'hello' && msg.state === 'ok') boundUserEl.textContent = `${{msg.user_id || '-'}} / ${{msg.device_id || '-'}}`;
        if (msg.type === 'stt' && ['partial', 'sentence_final', 'stream_final', 'final'].includes(msg.state)) sttEl.textContent = msg.text || '-';
        if (msg.type === 'agent' && msg.state === 'delta') replyEl.textContent = (replyEl.textContent === '-' ? '' : replyEl.textContent) + (msg.text || '');
        if (msg.type === 'agent' && msg.state === 'reply') replyEl.textContent = msg.text || '-';
        if (msg.type === 'tts' && msg.state === 'stop') {{
          timingEl.textContent = `首字 ${{msg.first_agent_delta_ms || '-'}}ms · 首段语音 ${{msg.first_tts_audio_ms || '-'}}ms · 总耗时 ${{msg.total_elapsed_ms}}ms`;
          recordBtn.disabled = false;
          recordBtn.textContent = '按住说话';
        }}
        if (msg.type === 'error') {{
          recordBtn.disabled = false;
          recordBtn.textContent = '按住说话';
        }}
      }};
    }};

    async function startRecording() {{
      if (!ws || ws.readyState !== WebSocket.OPEN) {{
        log('请先点击连接');
        return;
      }}
      if (recording || startingRecording) return;
      recordingRequested = true;
      startingRecording = true;
      recordBtn.classList.add('recording');
      recordBtn.textContent = '录音中';
      connectBtn.disabled = true;
      audioQueue = [];
      audioPlaying = false;
      sttEl.textContent = '-';
      replyEl.textContent = '-';
      timingEl.textContent = '-';
      try {{
        stream = await navigator.mediaDevices.getUserMedia({{audio: true}});
        audioContext = new AudioContext();
        source = audioContext.createMediaStreamSource(stream);
        processor = audioContext.createScriptProcessor(4096, 1, 1);
        processor.onaudioprocess = (event) => {{
          if (!recording || ws.readyState !== WebSocket.OPEN) return;
          const input = event.inputBuffer.getChannelData(0);
          const pcm = downsampleToPcm16(input, audioContext.sampleRate, 16000);
          if (pcm.byteLength) ws.send(pcm);
        }};
        source.connect(processor);
        processor.connect(audioContext.destination);
        startingRecording = false;
        if (!recordingRequested) {{
          await cleanupAudio();
          restoreReadyState();
          return;
        }}
        recording = true;
        ws.send(JSON.stringify({{type: 'listen', state: 'start'}}));
      }} catch (error) {{
        log(`麦克风启动失败: ${{error.message || error}}`);
        startingRecording = false;
        recordingRequested = false;
        recording = false;
        await cleanupAudio();
        restoreReadyState();
      }}
    }}

    async function stopRecording() {{
      if (!recording && !startingRecording && !recordingRequested) return;
      recordingRequested = false;
      if (startingRecording && !recording) {{
        recordBtn.textContent = '处理中';
        return;
      }}
      recording = false;
      recordBtn.classList.remove('recording');
      recordBtn.textContent = '处理中';
      recordBtn.disabled = true;
      if (ws && ws.readyState === WebSocket.OPEN) {{
        ws.send(JSON.stringify({{type: 'listen', state: 'stop'}}));
      }}
      await cleanupAudio();
      connectBtn.disabled = false;
    }}

    async function cleanupAudio() {{
      if (processor) processor.disconnect();
      if (source) source.disconnect();
      if (stream) stream.getTracks().forEach(track => track.stop());
      if (audioContext) await audioContext.close();
      processor = null;
      source = null;
      stream = null;
      audioContext = null;
    }}

    function restoreReadyState() {{
      recordBtn.classList.remove('recording');
      recordBtn.textContent = '按住说话';
      recordBtn.disabled = !ws || ws.readyState !== WebSocket.OPEN;
      connectBtn.disabled = false;
    }}

    recordBtn.addEventListener('pointerdown', (event) => {{
      event.preventDefault();
      recordBtn.setPointerCapture(event.pointerId);
      startRecording();
    }});
    recordBtn.addEventListener('pointerup', (event) => {{
      event.preventDefault();
      stopRecording();
    }});
    recordBtn.addEventListener('pointercancel', (event) => {{
      event.preventDefault();
      stopRecording();
    }});
    recordBtn.addEventListener('pointerleave', (event) => {{
      if (recording || startingRecording || recordingRequested) stopRecording();
    }});

    function downsampleToPcm16(input, fromRate, toRate) {{
      const ratio = fromRate / toRate;
      const length = Math.floor(input.length / ratio);
      const output = new Int16Array(length);
      for (let i = 0; i < length; i++) {{
        const sample = input[Math.floor(i * ratio)];
        const clamped = Math.max(-1, Math.min(1, sample));
        output[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
      }}
      return output.buffer;
    }}
  </script>
</body>
</html>"""


def main() -> None:
    args = build_parser().parse_args()
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError(
            "uvicorn is not installed. Add voice web dependencies and rebuild Docker."
        ) from exc
    app = create_app(args.device_config, args.users_config, args.default_device_id, args.out_dir)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
