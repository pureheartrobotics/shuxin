from __future__ import annotations

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
from shuxin.voice.api.miniapp_admin import miniapp_admin_router
from shuxin.voice.api.routers.exception_handlers import register_exception_handlers
from shuxin.voice.api.routers.user import router as user_router
from shuxin.voice.api.routers.payment import router as payment_router
from shuxin.voice.api.routers.companions import router as companions_router
from shuxin.voice.api.routers.mall import router as mall_router
from shuxin.voice.api.routers.mall_admin import router as mall_admin_router
from shuxin.voice.api.routers.factory import router as factory_router
from shuxin.voice.api.routers.admin import router as admin_router
from shuxin.voice.service import VoiceService
from shuxin.voice.api.ws_session import _VoiceWebSocketSession
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


def _ws_downlink_max_bytes() -> int:
    raw = int(os.environ.get("SHUXIN_WS_DOWNLINK_MAX_BYTES", DEFAULT_WS_DOWNLINK_MAX_BYTES))
    return max(256, min(raw, HARD_WS_DOWNLINK_MAX_BYTES))


def _ws_downlink_yield_seconds() -> float:
    raw = float(os.environ.get("SHUXIN_WS_DOWNLINK_YIELD_MS", "0"))
    return max(0.0, raw) / 1000.0


def _audio_retention_hours() -> int:
    raw = os.environ.get("SHUXIN_AUDIO_RETENTION_HOURS", str(DEFAULT_AUDIO_RETENTION_HOURS)).strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_AUDIO_RETENTION_HOURS


def _audio_retention_interval_sec() -> int:
    raw = os.environ.get(
        "SHUXIN_AUDIO_RETENTION_INTERVAL_SEC",
        str(DEFAULT_AUDIO_RETENTION_INTERVAL_SEC),
    ).strip()
    try:
        return max(60, int(raw))
    except ValueError:
        return DEFAULT_AUDIO_RETENTION_INTERVAL_SEC


def _location_cache_ttl_seconds() -> int:
    raw = os.environ.get(
        "SHUXIN_LOCATION_CACHE_TTL_SECONDS",
        str(DEFAULT_LOCATION_CACHE_TTL_SECONDS),
    ).strip()
    try:
        return max(60, int(raw))
    except ValueError:
        return DEFAULT_LOCATION_CACHE_TTL_SECONDS


def _factory_verify_log_retention_days() -> int:
    raw = os.environ.get(
        "SHUXIN_FACTORY_VERIFY_LOG_RETENTION_DAYS",
        str(DEFAULT_FACTORY_VERIFY_LOG_RETENTION_DAYS),
    ).strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_FACTORY_VERIFY_LOG_RETENTION_DAYS


async def _retention_loop(
    repo,
    *,
    interval_sec: int,
    retention_hours: int,
    factory_verify_log_retention_days: int,
) -> None:
    while True:
        try:
            if retention_hours > 0:
                result = await repo.purge_expired_audio_attachments(
                    retention_hours=retention_hours
                )
                if int(result.get("purged", 0)) > 0:
                    logger.info(
                        "purged expired audio attachments purged=%s bytes_freed=%s",
                        result.get("purged", 0),
                        result.get("bytes_freed", 0),
                    )
            if factory_verify_log_retention_days > 0:
                result = await repo.purge_expired_factory_verify_logs(
                    retention_days=factory_verify_log_retention_days
                )
                if int(result.get("purged", 0)) > 0:
                    logger.info(
                        "purged expired factory verify logs purged=%s",
                        result.get("purged", 0),
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("retention purge failed")
        await asyncio.sleep(interval_sec)


def build_parser() -> argparse.ArgumentParser:
    """构建 voice server 的命令行参数。

    这个入口主要给 Docker 常驻服务和本机无硬件测试使用。
    """
    parser = argparse.ArgumentParser(description="ChuXin voice WebSocket demo server")
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
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:
        raise RuntimeError(
            "FastAPI is not installed. Add voice web dependencies and rebuild Docker."
        ) from exc
    globals()["Request"] = Request
    globals()["WebSocket"] = WebSocket

    app = FastAPI(title="ChuXin Voice Demo")
    register_exception_handlers(app)
    _voice_static_dir = Path(__file__).resolve().parent / "static"
    app.mount(
        "/voice-static",
        StaticFiles(directory=str(_voice_static_dir)),
        name="voice_static",
    )
    app.include_router(miniapp_admin_router, prefix="/miniapp-admin", tags=["Miniapp Admin"])
    app.include_router(user_router)
    app.include_router(payment_router)
    app.include_router(companions_router)
    app.include_router(mall_router)
    app.include_router(mall_admin_router)
    app.include_router(factory_router)
    app.include_router(admin_router)
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
    app.state.admin_token = admin_token
    app.state.out_dir = out_dir
    app.state.adapter_registry = adapter_registry

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
        retention_hours = _audio_retention_hours()
        interval_sec = _audio_retention_interval_sec()
        factory_verify_log_retention_days = _factory_verify_log_retention_days()
        app.state.audio_retention_task = asyncio.create_task(
            _retention_loop(
                app.state.repo,
                interval_sec=interval_sec,
                retention_hours=retention_hours,
                factory_verify_log_retention_days=factory_verify_log_retention_days,
            )
        )
        from shuxin.voice.persistence.billing import BillingService
        app.state.billing = BillingService(app.state.repo)

    @app.on_event("shutdown")
    async def shutdown() -> None:
        task = getattr(app.state, "audio_retention_task", None)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if database_url:
            await db.close()

    def repo():
        value = getattr(app.state, "repo", None)
        if value is None:
            raise RuntimeError("voice repository is not initialized")
        return value

    def billing():
        value = getattr(app.state, "billing", None)
        if value is None:
            raise RuntimeError("billing service is not initialized")
        return value


    def require_admin(request: Request) -> None:
        provided = request.headers.get("X-Admin-Token") or request.cookies.get("shuxin_admin")
        if not admin_token:
            raise PermissionError("SHUXIN_ADMIN_TOKEN is required for admin access")
        if provided != admin_token:
            raise PermissionError("invalid admin token")

    @app.api_route("/", methods=["GET", "HEAD"])
    async def root_not_found():
        # 备案期主域名根路径：真 HTTP 404 HTML（可见「404 Not Found」），
        # 而非默认 JSON {"error":"Not Found"}；其它路由不受影响。
        # 观感对齐 nginx 默认错误页，但不带底部 nginx 字样。
        return HTMLResponse(
            "<html>\n"
            "<head><title>404 Not Found</title></head>\n"
            "<body>\n"
            "<center><h1>404 Not Found</h1></center>\n"
            "<hr>\n"
            "</body>\n"
            "</html>\n",
            status_code=404,
        )

    @app.get("/voice-demo")
    async def voice_demo():
        static_file = Path(__file__).resolve().parent / "static" / "demo.html"
        content = static_file.read_text(encoding="utf-8")
        content = content.replace("{{DEFAULT_DEVICE_ID}}", default_device_id)
        return HTMLResponse(content)

    @app.get("/admin")
    async def admin_page(request: Request):
        authenticated = False
        try:
            require_admin(request)
            authenticated = True
        except Exception:
            authenticated = False
        static_file = Path(__file__).resolve().parent / "static" / "admin.html"
        content = static_file.read_text(encoding="utf-8")
        content = content.replace("{{AUTHENTICATED}}", "true" if authenticated else "false")
        return HTMLResponse(content)

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

    @app.get("/health")
    async def health():
        return JSONResponse(
            {
                "status": "ok",
                "service": "shuxin-voice-demo",
                "storage": "postgres" if database_url else "yaml-fallback",
            }
        )

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
            app=app,
        )
        try:
            await session.run()
        except WebSocketDisconnect:
            pass
        finally:
            # receive() 既可能抛 WebSocketDisconnect，也可能返回 disconnect
            # 消息后正常结束；两条路径都必须 flush 记忆并释放 Agent。
            await session.shutdown()

    return app


_FACTORY_ACCEPTANCE_DISABLED = "factory acceptance mode: conversation disabled"


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
