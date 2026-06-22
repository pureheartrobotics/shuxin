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
from shuxin.voice.adapters import VoiceAdapterRegistry
from shuxin.voice.audio_files import AudioFileStore
from shuxin.voice.barcode import decode_barcode_image_base64, generate_code128_png
from shuxin.voice.config import DeviceConfigProvider, LLMDeviceConfig, merge_llm_device_config
from shuxin.voice.dmx_client import (
    QUOTA_EXHAUSTED_MESSAGE,
    default_platform_llm_config,
    voice_test_mode_enabled,
)
from shuxin.voice.db import PostgresDatabase
from shuxin.voice.local_repository import VoiceLocalRepository
from shuxin.voice.postgres_repository import VoicePostgresRepository
from shuxin.voice.opus_codec import (
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
from shuxin.voice.agents import DEFAULT_AGENT_ID
from shuxin.voice.tts_config import create_tts_provider_from_agent, create_tts_provider_from_device
from shuxin.voice.mbti_reveal import (
    build_device_intro_text,
    build_factory_verify_mbti_payload,
    needs_device_intro,
    needs_mbti_reveal,
)
from shuxin.voice import voice_session_registry as vsr
from shuxin.voice.service import VoiceService
from shuxin.voice.text_sanitize import has_unclosed_parenthesis, prepare_speakable_text
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
    except ImportError as exc:
        raise RuntimeError(
            "FastAPI is not installed. Add voice web dependencies and rebuild Docker."
        ) from exc
    globals()["Request"] = Request
    globals()["WebSocket"] = WebSocket

    app = FastAPI(title="ChuXin Voice Demo")
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

    @app.post("/api/factory/verify")
    async def factory_verify(request: Request):
        """工厂验收：扫 claim_code → 查 device_id → WS 下发 factory_verify → 等 ack。

        鉴权：session_token（需 metadata.factory_role = 'true'）。
        """
        import uuid as _uuid
        import asyncio as _asyncio

        try:
            payload = await request.json()
            session_token = str(payload.get("session_token") or "")
            claim_code = str(payload.get("claim_code") or "").strip()
            if not claim_code:
                return JSONResponse({"error": "claim_code is required"}, status_code=400)

            # 1. 校验操作员权限
            try:
                operator_user = await repo().factory_verify_user_has_role(session_token)
            except PermissionError as exc:
                return JSONResponse({"error": str(exc)}, status_code=403)

            # 2. claim_code → device_id
            try:
                lookup = await repo().factory_verify_lookup(claim_code)
            except ValueError as exc:
                return JSONResponse(
                    {
                        "result": "FAIL",
                        "reason": "claim_code_not_found",
                        "detail": str(exc),
                    }
                )
            device_id = lookup["device_id"]
            verify_id = str(_uuid.uuid4())
            device_metadata = dict(lookup.get("metadata") or {})

            def _log_meta() -> dict[str, Any]:
                meta: dict[str, Any] = {
                    "claim_code_status": lookup.get("claim_code_status", ""),
                }
                if lookup.get("mbti"):
                    meta["mbti"] = lookup["mbti"]
                if lookup.get("mbti_status"):
                    meta["mbti_status"] = lookup["mbti_status"]
                return meta

            async def _write_log(result: str, fail_reason: str = "") -> None:
                try:
                    await repo().factory_verify_log(
                        verify_id=verify_id,
                        claim_code=claim_code,
                        device_id=device_id,
                        operator_user=operator_user,
                        result=result,
                        fail_reason=fail_reason,
                        meta=_log_meta(),
                    )
                except Exception as log_exc:
                    logger.warning("factory_verify_log failed: %s", log_exc)

            async def _send_factory_verify_fail(reason: str) -> None:
                try:
                    await session._send_json(
                        {
                            "type": "factory_verify_fail",
                            "verify_id": verify_id,
                            "reason": reason,
                        }
                    )
                except Exception as send_exc:
                    logger.warning(
                        "factory_verify_fail send failed device=%s reason=%s error=%s",
                        device_id,
                        reason,
                        send_exc,
                    )

            # 3. 查找设备 WS session
            session = vsr.get_active_session(device_id)
            if session is None:
                await _write_log("FAIL", "device_offline")
                return JSONResponse(
                    {
                        "result": "FAIL",
                        "reason": "device_offline",
                        "device_id": device_id,
                        "verify_id": verify_id,
                    }
                )

            # 4. 申请并发锁（同设备同时只允许一个验收）
            event = vsr.factory_verify_start(device_id)
            if event is None:
                await _send_factory_verify_fail("verify_in_progress")
                return JSONResponse(
                    {
                        "result": "FAIL",
                        "reason": "verify_in_progress",
                        "device_id": device_id,
                        "verify_id": verify_id,
                    }
                )

            # 5. 下发 factory_verify 消息给设备
            try:
                await session._send_json(
                    {
                        "type": "factory_verify",
                        "verify_id": verify_id,
                        "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
                    }
                )
            except Exception as send_exc:
                vsr.factory_verify_cleanup(device_id)
                await _write_log("FAIL", f"send_failed: {send_exc}")
                await _send_factory_verify_fail("send_failed")
                return JSONResponse(
                    {
                        "result": "FAIL",
                        "reason": "send_failed",
                        "device_id": device_id,
                        "verify_id": verify_id,
                    }
                )

            # 6. 等待 factory_verify_ack（最多 10 秒）
            try:
                await _asyncio.wait_for(event.wait(), timeout=FACTORY_VERIFY_ACK_TIMEOUT_SECONDS)
                passed = True
            except _asyncio.TimeoutError:
                passed = False
            finally:
                vsr.factory_verify_cleanup(device_id)

            if passed:
                await _write_log("PASS")
                mbti_payload = build_factory_verify_mbti_payload(device_metadata)
                pass_body: dict[str, Any] = {
                    "result": "PASS",
                    "device_id": device_id,
                    "verify_id": verify_id,
                }
                if mbti_payload:
                    pass_body["mbti"] = mbti_payload
                else:
                    pass_body["warnings"] = ["mbti_missing"]
                return JSONResponse(pass_body)
            else:
                await _write_log("FAIL", "ack_timeout")
                return JSONResponse(
                    {
                        "result": "FAIL",
                        "reason": "ack_timeout",
                        "device_id": device_id,
                        "verify_id": verify_id,
                    }
                )

        except Exception as exc:
            logger.exception("factory_verify unexpected error")
            return JSONResponse({"error": str(exc)}, status_code=500)

    @app.get("/api/factory/verify/logs")
    async def factory_verify_logs(
        request: Request,
        device_id: str = "",
        limit: int = 50,
    ):
        """查询当前 QA 账号的验收历史（session_token 鉴权）。"""
        try:
            session_token = request.headers.get("X-Session-Token", "")
            operator_user = await repo().factory_verify_user_has_role(session_token)
            logs = await repo().factory_verify_logs_list(
                operator_user=operator_user,
                device_id=device_id,
                limit=min(max(1, limit), 200),
                retention_days=_factory_verify_log_retention_days(),
            )
            return JSONResponse({"items": logs, "total": len(logs)})
        except PermissionError as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/admin/api/factory/verify/summary")
    async def admin_factory_verify_summary(
        request: Request,
        device_id: str = "",
        operator_user: str = "",
        limit: int = 200,
    ):
        """Admin 维度验收日志查询（X-Admin-Token 鉴权）。"""
        try:
            require_admin(request)
            logs = await repo().factory_verify_logs_list(
                operator_user=operator_user,
                device_id=device_id,
                limit=min(max(1, limit), 500),
                retention_days=_factory_verify_log_retention_days(),
            )
            total = len(logs)
            passed = sum(1 for r in logs if r["result"] == "PASS")
            return JSONResponse(
                {
                    "total": total,
                    "passed": passed,
                    "failed": total - passed,
                    "items": logs,
                }
            )
        except PermissionError as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)
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

    @app.post("/api/users/quota")
    async def user_quota(request: Request):
        try:
            payload = await request.json()
            session_token = str(payload.get("session_token") or "")
            if not session_token:
                return JSONResponse({"error": "session_token is required"}, status_code=400)
            return JSONResponse(await repo().get_user_quota_by_session(session_token))
        except PermissionError as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/api/users/me")
    async def user_me(request: Request):
        try:
            payload = await request.json()
            session_token = str(payload.get("session_token") or "")
            if not session_token:
                return JSONResponse({"error": "session_token is required"}, status_code=400)
            return JSONResponse(await repo().get_user_profile_by_session(session_token))
        except PermissionError as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/api/payment/plans")
    async def payment_plans():
        try:
            plans = await repo().list_payment_plans(include_disabled=False)
            return JSONResponse({"items": [plan.to_public_dict() for plan in plans]})
        except Exception as exc:
            from shuxin.voice.payment_config import list_payment_plan_dicts

            return JSONResponse({"items": list_payment_plan_dicts()})

    @app.post("/api/payment/create-order")
    async def payment_create_order(request: Request):
        from shuxin.voice.wechat_pay import create_jsapi_payment, wechat_pay_configured, wechat_pay_mock_mode

        try:
            payload = await request.json()
            session_token = str(payload.get("session_token") or "")
            plan_id = str(payload.get("plan_id") or "")
            if not session_token:
                return JSONResponse({"error": "session_token is required"}, status_code=400)
            if not plan_id:
                return JSONResponse({"error": "plan_id is required"}, status_code=400)
            if wechat_pay_mock_mode():
                return JSONResponse(
                    {"error": "WeChat Pay is disabled while SHUXIN_WECHAT_MOCK=1"},
                    status_code=503,
                )
            if not wechat_pay_configured():
                return JSONResponse({"error": "WeChat Pay is not configured"}, status_code=503)

            order = await repo().create_payment_order(session_token=session_token, plan_id=plan_id)
            plan_payload = dict(order.get("plan") or {})
            amount_fen = int(plan_payload.get("amount_fen") or 0)
            plan_name = str(plan_payload.get("name") or plan_id)
            if amount_fen <= 0:
                raise ValueError(f"invalid plan amount for: {plan_id}")
            prepay = create_jsapi_payment(
                description=f"初心{plan_name}",
                out_trade_no=str(order["out_trade_no"]),
                amount_fen=amount_fen,
                payer_openid=str(order["user_id"]),
            )
            await repo().attach_prepay_id(
                out_trade_no=str(order["out_trade_no"]),
                prepay_id=str(prepay["prepay_id"]),
            )
            pay_params = dict(prepay.get("pay_params") or {})
            return JSONResponse(
                {
                    "order": order,
                    "prepay_id": prepay["prepay_id"],
                    "pay_params": pay_params,
                }
            )
        except PermissionError as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            logger.exception("payment create-order failed")
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/api/payment/orders")
    async def payment_orders(request: Request):
        try:
            payload = await request.json()
            session_token = str(payload.get("session_token") or "")
            if not session_token:
                return JSONResponse({"error": "session_token is required"}, status_code=400)
            limit = int(payload.get("limit") or 20)
            return JSONResponse(
                await repo().list_payment_orders_by_session(session_token, limit=limit)
            )
        except PermissionError as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/api/payment/notify")
    async def payment_notify(request: Request):
        from shuxin.voice.wechat_pay import parse_payment_notify

        body = await request.body()
        headers = {key: value for key, value in request.headers.items()}
        try:
            payload = parse_payment_notify(headers, body)
            out_trade_no = str(payload.get("out_trade_no") or "")
            wx_transaction_id = str(payload.get("transaction_id") or "")
            if not out_trade_no:
                return JSONResponse({"code": "FAIL", "message": "missing out_trade_no"}, status_code=400)
            await repo().fulfill_payment_order(
                out_trade_no=out_trade_no,
                wx_transaction_id=wx_transaction_id,
                notify_payload=payload,
            )
            return JSONResponse({"code": "SUCCESS", "message": "成功"})
        except Exception as exc:
            logger.exception("payment notify failed")
            return JSONResponse({"code": "FAIL", "message": str(exc)}, status_code=400)

    @app.post("/api/devices/bind")
    async def bind_device(request: Request):
        try:
            payload = await request.json()
            session_token = str(payload.get("session_token") or "")
            if session_token:
                quota = await repo().get_user_quota_by_session(session_token)
                if quota.get("exhausted"):
                    return JSONResponse({"error": QUOTA_EXHAUSTED_MESSAGE}, status_code=403)
            result = await repo().bind_device(
                wx_code=str(payload.get("wx_code") or ""),
                session_token=session_token,
                claim_code=str(payload.get("claim_code") or ""),
                device_code=str(payload.get("device_code") or ""),
            )
            await vsr.maybe_push_intro_after_bind(result)
            return JSONResponse(result)
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

    @app.post("/admin/api/devices/apply-stt-defaults")
    async def admin_apply_stt_defaults(request: Request):
        try:
            require_admin(request)
            return JSONResponse(await repo().apply_default_stt_to_all_devices())
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/admin/api/devices/apply-tts-defaults")
    async def admin_apply_tts_defaults(request: Request):
        try:
            require_admin(request)
            return JSONResponse(await repo().apply_default_tts_to_all_devices())
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/admin/api/agents")
    async def admin_list_agents(request: Request, limit: int = 50, cursor: str = "", q: str = ""):
        try:
            require_admin(request)
            return JSONResponse(await repo().list_agents(limit=limit, cursor=cursor, q=q))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)

    @app.post("/admin/api/agents")
    async def admin_create_agent(request: Request):
        try:
            require_admin(request)
            payload = await request.json()
            return JSONResponse(await repo().create_agent(payload))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/admin/api/agents/{agent_id}")
    async def admin_get_agent(request: Request, agent_id: str):
        try:
            require_admin(request)
            record = await repo().get_agent(agent_id)
            return JSONResponse(record.to_admin_dict())
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)

    @app.patch("/admin/api/agents/{agent_id}")
    async def admin_update_agent(request: Request, agent_id: str):
        try:
            require_admin(request)
            payload = await request.json()
            return JSONResponse(await repo().update_agent(agent_id, payload))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.delete("/admin/api/agents/{agent_id}")
    async def admin_delete_agent(request: Request, agent_id: str):
        try:
            require_admin(request)
            await repo().soft_delete_agent(agent_id)
            return JSONResponse({"ok": True})
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.patch("/admin/api/users/{user_id}")
    async def admin_patch_user(request: Request, user_id: str):
        try:
            require_admin(request)
            payload = await request.json()
            return JSONResponse(await repo().patch_user(user_id, payload))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.patch("/admin/api/users/{user_id}/voice-preferences")
    async def admin_user_voice_preferences(request: Request, user_id: str):
        del request, user_id
        return JSONResponse(
            {"error": "voice-preferences API reserved for future user-facing customization"},
            status_code=501,
        )

    @app.post("/admin/api/tts/preview")
    async def admin_tts_preview(request: Request):
        try:
            require_admin(request)
            payload = await request.json()
            agent_id = str(payload.get("agent_id") or DEFAULT_AGENT_ID)
            text = str(payload.get("text") or "你好，这是音色试听。")
            agent_record = await repo().get_agent(agent_id)
            preview_dir = out_dir / "admin-preview"
            preview_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{uuid.uuid4().hex}.mp3"
            path = preview_dir / filename
            provider = create_tts_provider_from_agent(agent_record, output_dir=str(preview_dir))
            await provider.synthesize(text, path)
            return JSONResponse(
                {
                    "agent_id": agent_id,
                    "text": text,
                    "audio_path": str(path),
                    "audio_url": f"/admin/api/tts/preview/files/{filename}",
                }
            )
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/admin/api/tts/preview/files/{filename}")
    async def admin_tts_preview_file(request: Request, filename: str):
        try:
            require_admin(request)
            safe_name = Path(filename).name
            path = out_dir / "admin-preview" / safe_name
            if not path.is_file():
                return JSONResponse({"error": "preview file not found"}, status_code=404)
            from fastapi.responses import FileResponse

            return FileResponse(path, media_type="audio/mpeg", filename=safe_name)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)

    @app.patch("/admin/api/devices/{device_id}")
    async def admin_update_device_label(request: Request, device_id: str):
        try:
            require_admin(request)
            payload = await request.json()
            return JSONResponse(await repo().update_device_label(device_id, payload))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.patch("/admin/api/devices/{device_id}/mbti")
    async def admin_update_device_mbti(request: Request, device_id: str):
        try:
            require_admin(request)
            payload = await request.json()
            return JSONResponse(await repo().update_device_mbti(device_id, payload))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/admin/api/mbti/types")
    async def admin_list_mbti_types(request: Request):
        try:
            require_admin(request)
            profiles = load_mbti_profiles()
            items = [
                {"type": mbti, "tagline": str(entry.get("tagline") or "")}
                for mbti, entry in sorted(profiles.items())
            ]
            return JSONResponse({"items": items})
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

    @app.get("/admin/api/devices/{device_id}/secret")
    async def admin_reveal_device_secret(request: Request, device_id: str):
        try:
            require_admin(request)
            return JSONResponse(await repo().reveal_device_secret(device_id))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/admin/api/voice-demo/targets")
    async def admin_voice_demo_targets(request: Request):
        try:
            require_admin(request)
            return JSONResponse(await repo().list_voice_demo_targets())
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)

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

    @app.get("/admin/api/users/{user_id}/quota")
    async def admin_user_quota(request: Request, user_id: str):
        try:
            require_admin(request)
            return JSONResponse(await repo().get_user_quota_by_user_id(user_id, admin_detail=True))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/admin/api/payment/plans")
    async def admin_list_payment_plans(request: Request):
        try:
            require_admin(request)
            plans = await repo().list_payment_plans(include_disabled=True)
            return JSONResponse({"items": [plan.to_admin_dict() for plan in plans]})
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/admin/api/payment/plans")
    async def admin_create_payment_plan(request: Request):
        try:
            require_admin(request)
            payload = await request.json()
            return JSONResponse(await repo().create_payment_plan(payload))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.patch("/admin/api/payment/plans/{plan_id}")
    async def admin_update_payment_plan(request: Request, plan_id: str):
        try:
            require_admin(request)
            payload = await request.json()
            return JSONResponse(await repo().update_payment_plan(plan_id, payload))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.delete("/admin/api/payment/plans/{plan_id}")
    async def admin_delete_payment_plan(request: Request, plan_id: str):
        try:
            require_admin(request)
            return JSONResponse(await repo().soft_delete_payment_plan(plan_id))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/admin/api/platform/payment-settings")
    async def admin_get_payment_settings(request: Request):
        try:
            require_admin(request)
            return JSONResponse(await repo().get_payment_settings())
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.patch("/admin/api/platform/payment-settings")
    async def admin_update_payment_settings(request: Request):
        try:
            require_admin(request)
            payload = await request.json()
            ratio = float(payload.get("credit_ratio") or 0)
            return JSONResponse(await repo().set_credit_ratio(ratio))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/admin/api/users/{user_id}/quota/top-up")
    async def admin_user_quota_top_up(request: Request, user_id: str):
        try:
            require_admin(request)
            payload = await request.json()
            return JSONResponse(
                await repo().top_up_user_dmx_quota(
                    user_id,
                    add_yuan=float(payload.get("add_yuan") or 0),
                    note=str(payload.get("note") or ""),
                )
            )
        except PermissionError as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/admin/api/platform/llm-defaults")
    async def admin_platform_llm_defaults(request: Request):
        try:
            require_admin(request)
            return JSONResponse(default_platform_llm_config())
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)

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


_FACTORY_ACCEPTANCE_DISABLED = "factory acceptance mode: conversation disabled"


def _client_ip_from_websocket(websocket) -> str:
    """从 WebSocket 连接解析客户端 IP（支持 X-Forwarded-For）。"""
    forwarded = websocket.headers.get("x-forwarded-for") or websocket.headers.get(
        "X-Forwarded-For"
    )
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
        self.agent_record = None
        self.audio_chunks: list[bytes] = []
        self.realtime_asr: TencentRealtimeASRSession | None = None
        self.realtime_stt_started = 0.0
        self.listening = False
        self.audio_wire_format = "pcm"
        self.audio_params: dict[str, int | str] = _negotiate_audio_params(None)
        self.opus_uplink_decoder: OpusStreamDecoder | None = None
        self.hardware_session = False
        self.factory_acceptance = False
        self.client_ip = _client_ip_from_websocket(websocket)
        self._location_cache: dict | None = None

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
        if self.user_settings is not None:
            try:
                await self.repo.maybe_merge_rolling_summary(
                    self.user_settings,
                    self.device,
                    force=True,
                )
            except Exception:
                pass
        if self.realtime_asr is not None:
            await self.realtime_asr.close()
            self.realtime_asr = None
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

        if message_type == "hello":
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
            self.audio_store = AudioFileStore(self.shuxin_home, self.out_dir, self.user_id)
            self.session_id = data.get("session_id") or uuid.uuid4().hex
            if not self.factory_acceptance:
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
                try:
                    await self._maybe_reveal_mbti_on_hello()
                except Exception as exc:
                    logger.warning("mbti reveal on hello failed: %s", exc)
            return

        if self.factory_acceptance and message_type in {"listen", "text_turn"}:
            await self._send_json({"type": "error", "message": _FACTORY_ACCEPTANCE_DISABLED})
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

        if message_type == "text_turn":
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
            return

        if message_type == "factory_verify_ack":
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
            return

        if message_type == "ping":
            await self._send_json({"type": "pong", "ts": time.time()})
            return

        await self._send_json({"type": "error", "message": f"unsupported message: {data}"})

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
            if self.realtime_asr is not None:
                await self.realtime_asr.send_audio(pcm_frame)

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
                self.agent.context.metadata.pop("map_tool_ms", None)
            location_started = time.perf_counter()
            await self._refresh_location_context(text)
            location_ms = _elapsed_ms(location_started)

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
            await self._send_json({"type": "error", "message": str(exc)})
        finally:
            self.audio_chunks = []

    async def _process_text_turn(self, text: str) -> None:
        """E2E/开发用：跳过 STT，直接以文本触发一轮 Agent（需 SHUXIN_VOICE_DEV_TEXT_TURN=1）。"""
        started = time.perf_counter()
        skip_tts = os.environ.get("SHUXIN_VOICE_E2E_SKIP_TTS") == "1"
        try:
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
                speech_path = await self._synthesize_and_send_sentence(
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
            await self._send_json({"type": "error", "message": str(exc)})

    async def _reset_runtime(self) -> None:
        """切换用户或设备时重建运行态，确保配置和记忆目录重新绑定。"""
        await self.shutdown(mark_offline=False)
        self.stt = None
        self.tts = None
        self.device = None
        self.agent_record = None

    async def _maybe_reveal_mbti_on_hello(self) -> None:
        """开箱或补播：sealed 时揭晓+TTS；小程序已揭晓时仅补播自我介绍。"""
        device = await self.repo.get_device(self.device_id)
        self.device = device
        metadata = device.metadata or {}

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
            device = await self.repo.get_device(self.device_id)
            self.device = device
            metadata = device.metadata or {}
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
        await self._synthesize_and_send_sentence(text, output_path, 1, started)
        await self._send_json(
            {
                "type": "tts",
                "state": "stop",
                "elapsed_ms": _elapsed_ms(tts_started),
                "total_elapsed_ms": _elapsed_ms(started),
            }
        )

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
        clean_text = prepare_speakable_text(text)
        if not clean_text:
            output_path.write_bytes(b"")
            await asyncio.sleep(0.01)
            await self._send_json(
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

        sentence_started = time.perf_counter()
        speech_path = await self.tts.synthesize(clean_text, output_path)
        if self._uses_opus_downlink():
            await self._send_opus_downlink_stream(speech_path)
        else:
            await self._send_downlink_bytes(speech_path.read_bytes())
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

    def _is_web_demo_client(self) -> bool:
        return (self.client_id or "web-demo") == "web-demo"

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
        if self.agent is None:
            if hasattr(self.repo, "assert_user_quota_available"):
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
            )
            self.agent.context.metadata["channel"] = "voice"
            self.agent.context.metadata["agent_id"] = self.agent_record.agent_id
            self.agent.context.metadata["client_ip"] = self.client_ip
            self._setup_agent_tool_callbacks()
            await asyncio.to_thread(self.agent.initialize)
            VoiceService.apply_device_mbti(self.agent, self.device, self.agent_record)

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

    async def _send_json(self, data: dict) -> None:
        """以 UTF-8 JSON 文本消息下发状态，保留中文错误和回复内容。"""
        await self.websocket.send_text(json.dumps(data, ensure_ascii=False))


def _elapsed_ms(started: float) -> int:
    """把 perf_counter 起点转换为毫秒耗时，便于前端展示链路耗时。"""
    return int((time.perf_counter() - started) * 1000)


def _admin_html(authenticated: bool) -> str:
    """返回轻量后台页面；所有数据操作仍走 /admin/api。"""
    auth_state = "true" if authenticated else "false"
    platform_llm = default_platform_llm_config()
    platform_model = platform_llm.get("model", "deepseek-chat")
    platform_base_url = platform_llm.get("base_url", "https://www.dmxapi.cn")
    voice_test_mode = "true" if voice_test_mode_enabled() else "false"
    users_test_hint = (
        '<p class="hint" style="margin:0 0 12px;color:#9e3b35">'
        "测试模式已开启（SHUXIN_VOICE_TEST_MODE=1）：删除用户将真删（解绑设备、清 DB 记忆），"
        "便于验证 DMX 重新开通。"
        "</p>"
        if voice_test_mode == "true"
        else ""
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ChuXin 管理后台</title>
  <style>
    :root {{
      --bg: #f5f5f7;
      --surface: #ffffff;
      --text: #1d1d1f;
      --text-secondary: #6e6e73;
      --accent: #0071e3;
      --accent-hover: #0077ed;
      --destructive: #ff3b30;
      --separator: rgba(0, 0, 0, .08);
      --radius: 12px;
      --radius-sm: 8px;
      --shadow: 0 2px 16px rgba(0, 0, 0, .06);
      --font: -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Helvetica Neue", sans-serif;
      --mono: ui-monospace, SFMono-Regular, Menlo, monospace;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: var(--font); color: var(--text); background: var(--bg); -webkit-font-smoothing: antialiased; }}
    header {{
      height: 52px; display: flex; align-items: center; justify-content: space-between; padding: 0 24px;
      border-bottom: 1px solid var(--separator); background: rgba(255, 255, 255, .72);
      backdrop-filter: saturate(180%) blur(20px); position: sticky; top: 0; z-index: 100;
    }}
    main {{ max-width: 1080px; margin: 0 auto; padding: 24px 20px 48px; }}
    h1 {{ font-size: 17px; font-weight: 600; margin: 0; letter-spacing: -.02em; }}
    h2 {{ font-size: 15px; font-weight: 600; margin: 0 0 12px; letter-spacing: -.01em; }}
    input, textarea, select {{
      width: 100%; border: 1px solid var(--separator); border-radius: var(--radius-sm);
      padding: 8px 11px; font: inherit; background: var(--surface); color: var(--text);
      transition: border-color .15s ease, box-shadow .15s ease;
    }}
    input:focus, textarea:focus, select:focus {{
      outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(0, 113, 227, .15);
    }}
    textarea {{ min-height: 130px; font-family: var(--mono); font-size: 13px; }}
    button {{
      height: 32px; border: 0; border-radius: 980px; padding: 0 14px; font-size: 13px; font-weight: 500;
      color: #fff; background: var(--accent); cursor: pointer; transition: background .15s ease, opacity .15s ease;
    }}
    button:hover {{ background: var(--accent-hover); }}
    button:disabled {{ cursor: not-allowed; opacity: .45; }}
    button.secondary {{ color: var(--text); background: rgba(0, 0, 0, .06); }}
    button.secondary:hover {{ background: rgba(0, 0, 0, .1); }}
    button.ghost {{ height: 28px; padding: 0 10px; font-size: 12px; color: var(--accent); background: transparent; }}
    button.ghost:hover {{ background: rgba(0, 113, 227, .08); }}
    button.danger {{ background: var(--destructive); }}
    button.btn-destructive {{
      height: auto; padding: 6px 12px; color: var(--destructive); background: transparent; border-radius: var(--radius-sm);
    }}
    button.btn-destructive:hover {{ background: rgba(255, 59, 48, .08); }}
    .grid {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, 420px); gap: 16px; align-items: start; }}
    .stack {{ display: grid; gap: 16px; }}
    .panel {{
      background: var(--surface); border: 1px solid var(--separator); border-radius: var(--radius);
      padding: 18px 20px; box-shadow: var(--shadow);
    }}
    .toolbar {{ display: flex; gap: 8px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }}
    .toolbar input {{ min-width: 200px; flex: 1; }}
    .toolbar select {{ width: 86px; flex: 0 0 auto; }}
    .pager {{ display: flex; gap: 8px; align-items: center; justify-content: flex-end; margin-top: 12px; }}
    .page-size {{ width: 86px; }}
    .form-row {{ display: grid; grid-template-columns: repeat(6, minmax(110px, 1fr)); gap: 8px; align-items: end; }}
    .form-row.compact {{ grid-template-columns: repeat(5, minmax(130px, 1fr)); }}
    .table {{ display: grid; gap: 6px; overflow-x: auto; }}
    .table-row {{ display: grid; gap: 8px; align-items: center; padding: 10px 0; border-bottom: 1px solid var(--separator); }}
    .table-row > * {{ min-width: 0; }}
    .table-row.users {{ grid-template-columns: minmax(180px, 0.75fr) minmax(140px, 0.55fr) 70px 72px 90px 120px minmax(180px, 1fr) minmax(260px, 1fr); min-width: 1092px; }}
    .table-row.bindings {{ grid-template-columns: minmax(200px, 1fr) 150px 170px 90px 70px 100px; min-width: 760px; }}
    .table-head {{ color: var(--text-secondary); font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; }}
    .login {{ max-width: 400px; margin: 72px auto 0; }}
    .list {{ display: grid; gap: 8px; }}
    .item {{ display: grid; grid-template-columns: 1fr auto; gap: 12px; align-items: center; padding: 10px 0; border-bottom: 1px solid var(--separator); }}
    .item.selectable {{ padding: 12px 14px; border: 1px solid var(--separator); border-radius: var(--radius-sm); background: var(--surface); cursor: pointer; }}
    .item.selectable:hover {{ border-color: rgba(0, 113, 227, .35); }}
    .item.selected {{ border-color: var(--accent); background: rgba(0, 113, 227, .04); }}
    .item.muted {{ opacity: .55; pointer-events: none; }}
    .meta {{ color: var(--text-secondary); font-size: 12px; margin-top: 3px; }}
    .meta-line {{ color: var(--text-secondary); font-size: 13px; margin-bottom: 4px; }}
    .badge-row {{ display: flex; flex-wrap: wrap; gap: 6px; min-width: 0; }}
    .badge {{
      display: inline-flex; align-items: center; height: 22px; padding: 0 9px; border-radius: 999px;
      font-size: 11px; font-weight: 500; color: var(--accent); background: rgba(0, 113, 227, .1);
    }}
    .badge.warn {{ color: #bf4800; background: rgba(191, 72, 0, .1); }}
    .callout.warn {{
      background: rgba(191, 72, 0, .08); border: 1px solid rgba(191, 72, 0, .22);
      border-radius: 10px; padding: 12px 14px; margin-bottom: 12px; font-size: 13px; color: #bf4800;
    }}
    .badge.off {{ color: var(--text-secondary); background: rgba(0, 0, 0, .06); }}
    .badge.badge-click {{ cursor: pointer; }}
    .badge.badge-click:hover {{ filter: brightness(.96); }}
    .cell-clip {{ min-width: 0; overflow: hidden; cursor: pointer; border-radius: 6px; padding: 2px 0; }}
    .cell-clip strong {{
      display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
      font-family: var(--mono); font-size: 13px; font-weight: 600;
    }}
    .cell-clip:hover strong {{ color: var(--accent); }}
    .cell-clip.cell-secret {{
      padding: 8px 10px; border: 1px dashed var(--separator); border-radius: var(--radius-sm); background: rgba(0, 0, 0, .02);
    }}
    .cell-clip.cell-secret:hover {{ border-color: var(--accent); background: rgba(0, 113, 227, .04); }}
    .device-cards {{ display: grid; gap: 12px; }}
    .device-card {{
      background: var(--surface); border: 1px solid var(--separator); border-radius: var(--radius);
      padding: 16px 18px; box-shadow: var(--shadow);
    }}
    .device-card-head {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 14px; }}
    .device-card-id {{ flex: 1; min-width: 0; }}
    .device-card-body {{ display: grid; gap: 14px; }}
    .device-card-section {{ display: grid; gap: 6px; }}
    .field-label {{ font-size: 11px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: .05em; }}
    .readonly-field {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
    .claim-code {{
      font-family: var(--mono); font-size: 13px; padding: 6px 10px; border-radius: var(--radius-sm);
      background: rgba(0, 0, 0, .04); color: var(--text);
    }}
    .device-card-mbti {{ display: flex; gap: 8px; align-items: center; }}
    .device-card-mbti select {{ flex: 1; }}
    .device-card-note textarea {{ min-height: 56px; resize: vertical; font-family: var(--font); font-size: 14px; }}
    .device-card-footer {{ display: flex; justify-content: flex-end; align-items: center; margin-top: 4px; padding-top: 12px; border-top: 1px solid var(--separator); }}
    .llm-form {{ display: grid; gap: 12px; }}
    .llm-form label {{ display: grid; gap: 4px; }}
    .llm-form input {{ width: 100%; }}
    .modal-backdrop {{ display: none; position: fixed; inset: 0; z-index: 1000; background: rgba(0, 0, 0, .35); align-items: center; justify-content: center; padding: 24px; }}
    .modal-backdrop.open {{ display: flex; animation: modalFade .18s ease; }}
    .modal-panel {{
      width: min(520px, 100%); max-height: min(80vh, 640px); overflow: auto; background: var(--surface);
      border: 1px solid var(--separator); border-radius: var(--radius); padding: 20px 22px; box-shadow: 0 24px 64px rgba(0, 0, 0, .18);
    }}
    .modal-header {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }}
    .modal-header h3 {{ margin: 0; font-size: 17px; font-weight: 600; }}
    .modal-body-text {{
      font-family: var(--mono); font-size: 13px; word-break: break-all; white-space: pre-wrap;
      background: rgba(0, 0, 0, .03); border: 1px solid var(--separator); border-radius: var(--radius-sm); padding: 12px;
    }}
    .modal-actions {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }}
    .modal-close {{ height: 32px; }}
    @keyframes modalFade {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
    .tabs {{
      display: inline-flex; gap: 2px; margin-bottom: 20px; padding: 3px;
      background: rgba(0, 0, 0, .06); border-radius: 980px;
    }}
    .tabs button {{
      height: 32px; padding: 0 16px; color: var(--text-secondary); background: transparent; border-radius: 980px;
    }}
    .tabs button:hover {{ color: var(--text); background: rgba(255, 255, 255, .5); }}
    .tabs button.active {{ color: var(--text); background: var(--surface); box-shadow: 0 1px 4px rgba(0, 0, 0, .08); }}
    .bind-board {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(240px, 300px) minmax(0, 1fr); gap: 14px; align-items: start; }}
    .bind-action {{ display: grid; gap: 10px; }}
    .bind-summary {{ min-height: 120px; padding: 12px; border: 1px dashed var(--separator); border-radius: var(--radius-sm); background: rgba(0, 0, 0, .02); }}
    .hint {{ color: var(--text-secondary); font-size: 13px; line-height: 1.55; }}
    pre {{ white-space: pre-wrap; margin: 0; font-size: 13px; }}
    .header-link {{ color: var(--accent); text-decoration: none; font-size: 13px; font-weight: 500; }}
    .header-link:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <header><h1>ChuXin 管理后台</h1><div class="toolbar" style="margin:0"><a href="/voice-demo" class="header-link">语音测试台</a><button class="secondary" onclick="loadAll()">刷新</button></div></header>
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
        <button id="tabAgents" onclick="showTab('agents')">Agent</button>
        <button id="tabPaymentPlans" onclick="showTab('paymentPlans')">充值套餐</button>
        <button id="tabBindings" onclick="showTab('bindings')">绑定</button>
        <button id="tabAdapters" onclick="showTab('adapters')">适配器</button>
      </div>
      <div id="devices" class="stack">
        <div class="panel">
          <h2>批量制码</h2>
          <div id="batchEncryptionBanner" class="callout warn" style="display:none">
            未配置设备密钥加密（<code>SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY</code>）。批量制码将无法入库可查看密钥。
            请在 <code>.env</code> 生成 Fernet 密钥后重部署 Docker，再重新制码。
          </div>
          <div class="form-row">
            <label><span class="hint">设备前缀</span><input id="batchDevicePrefix" value="SX" onchange="refreshBatchStart()" /></label>
            <label><span class="hint">起始编号</span><input id="batchStart" type="number" value="1" min="1" /></label>
            <label><span class="hint">外壳码前缀</span><input id="batchLabelPrefix" value="CLM" /></label>
            <label><span class="hint">批次</span><input id="batchLabelBatch" value="A001" /></label>
            <label><span class="hint">数量</span><input id="batchQuantity" type="number" value="3" min="1" max="500" /></label>
            <button onclick="provisionBatch()">生成并入库</button>
          </div>
          <div class="toolbar" style="margin-top:12px"><button class="secondary" onclick="downloadBatchCsv()">下载本批 CSV</button><span id="batchNextHint" class="hint">批量结果会显示明文；入库后也可在设备列表「查看」密钥（需配置 SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY）。</span></div>
          <div id="batchResult" class="table"></div>
        </div>
        <div class="panel">
          <div class="toolbar" style="justify-content:space-between">
            <h2>设备状态与配置</h2>
            <div class="toolbar" style="margin-bottom:0">
              <button class="secondary" onclick="applyTencentSttDefaults()">全部应用腾讯 STT</button>
              <button class="secondary" onclick="applyVolcTtsDefaults()">全部应用火山 TTS</button>
              <input id="devicesSearch" placeholder="查找设备 / 外壳码 / 备注" />
              <select id="devicesLimit" class="page-size"><option value="20">20</option><option value="50">50</option></select>
              <button class="secondary" onclick="resetList('devices')">查找</button>
            </div>
          </div>
          <p class="hint" style="margin:0 0 12px">外壳码印在设备外壳上，仅展示不可修改。解绑后认领码自动恢复可扫码。</p>
          <div id="deviceList" class="device-cards"></div>
          <div id="devicesPager" class="pager"></div>
        </div>
      </div>
      <div id="users" class="stack" style="display:none">
        <div class="panel">
          <h2>新增用户与模型配置</h2>
          <div class="form-row compact">
            <label><span class="hint">用户 ID</span><input id="newUserId" value="demo-user" /></label>
            <label><span class="hint">模型</span><input id="newModel" placeholder="{platform_model}" /></label>
            <label><span class="hint">Base URL</span><input id="newBaseUrl" placeholder="{platform_base_url}" /></label>
            <label><span class="hint">API Key</span><input id="newApiKey" type="password" placeholder="只保存，不回显" /></label>
          </div>
          <div class="toolbar" style="margin-top:12px"><button onclick="createUser()">保存用户</button></div>
        </div>
        <div class="panel">
          {users_test_hint}
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
      <div id="agents" class="stack" style="display:none">
        <div class="panel">
          <h2>新建 Agent</h2>
          <div class="form-row compact">
            <label><span class="hint">Agent ID</span><input id="newAgentId" placeholder="guardian" /></label>
            <label><span class="hint">显示名</span><input id="newAgentName" placeholder="守护灵" /></label>
            <label><span class="hint">voice_type</span><input id="newAgentVoice" placeholder="火山复刻 ID" /></label>
            <label><span class="hint">cluster</span><input id="newAgentCluster" value="volcano_icl" /></label>
            <label><span class="hint">soul_path</span><input id="newAgentSoul" placeholder="data/agents/shuxin/SOUL.md" /></label>
          </div>
          <div class="toolbar" style="margin-top:12px"><button onclick="createAgent()">保存 Agent</button></div>
        </div>
        <div class="panel">
          <div class="toolbar" style="justify-content:space-between">
            <h2>Agent 音色与人格</h2>
            <div class="toolbar" style="margin-bottom:0">
              <input id="agentsSearch" placeholder="查找 Agent" />
              <select id="agentsLimit" class="page-size"><option value="20">20</option><option value="50">50</option></select>
              <button class="secondary" onclick="resetList('agents')">查找</button>
            </div>
          </div>
          <div id="agentList" class="table"></div>
          <div id="agentsPager" class="pager"></div>
        </div>
      </div>
      <div id="paymentPlans" class="stack" style="display:none">
        <div class="panel">
          <h2>全局到账比例</h2>
          <div class="form-row compact">
            <label><span class="hint">credit_ratio（0.01–1.00）</span><input id="creditRatio" type="number" min="0.01" max="1" step="0.01" value="0.95" /></label>
            <button onclick="saveCreditRatio()">保存比例</button>
          </div>
          <p class="hint" style="margin:8px 0 0">用户付 100 元 → 界面余额 +100，DMX 实际 +100×比例。仅影响<strong>新创建</strong>订单；履约使用下单时快照。</p>
        </div>
        <div class="panel">
          <h2>新增充值档位</h2>
          <div class="form-row compact">
            <label><span class="hint">plan_id</span><input id="newPlanId" placeholder="plan_100" /></label>
            <label><span class="hint">名称</span><input id="newPlanName" placeholder="100 元档" /></label>
            <label><span class="hint">支付价（分）</span><input id="newPlanAmountFen" type="number" min="1" placeholder="10000" /></label>
            <label><span class="hint">排序</span><input id="newPlanSort" type="number" value="0" /></label>
            <label><span class="hint">描述</span><input id="newPlanDesc" placeholder="可选" /></label>
          </div>
          <div class="toolbar" style="margin-top:12px"><button onclick="createPaymentPlan()">保存档位</button></div>
        </div>
        <div class="panel">
          <div class="toolbar" style="justify-content:space-between">
            <h2>充值套餐列表</h2>
            <button class="secondary" onclick="loadPaymentPlans()">刷新</button>
          </div>
          <div id="paymentPlanList" class="table"></div>
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
              <div class="toolbar" style="margin-bottom:8px">
                <input id="bindUsersSearch" placeholder="查找用户 / 模型" />
                <select id="bindUsersLimit" class="page-size"><option value="10">10</option><option value="20" selected>20</option><option value="50">50</option></select>
                <button class="secondary" onclick="resetList('bindUsers')">查找</button>
              </div>
              <div id="bindUserList" class="list"></div>
              <div id="bindUsersPager" class="pager"></div>
            </section>
            <section class="bind-action">
              <h2>绑定操作</h2>
              <div id="bindSummary" class="bind-summary hint">先选择一个用户，再选择一台未绑定设备。</div>
              <button id="bindSelectedBtn" onclick="bindSelected()" disabled>绑定所选</button>
              <div class="hint">用户 token 仅用于旧 demo 兼容；小程序和真实硬件使用微信 openid 与设备绑定关系。</div>
            </section>
            <section>
              <h2>选择设备</h2>
              <div class="toolbar" style="margin-bottom:8px">
                <input id="bindDevicesSearch" placeholder="查找设备 / 外壳码 / 备注" />
                <select id="bindDevicesLimit" class="page-size"><option value="10">10</option><option value="20" selected>20</option><option value="50">50</option></select>
                <button class="secondary" onclick="resetList('bindDevices')">查找</button>
              </div>
              <div id="bindDeviceList" class="list"></div>
              <div id="bindDevicesPager" class="pager"></div>
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
          <div id="bindingList" class="table"></div>
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
  <div id="adminModal" class="modal-backdrop" onclick="if(event.target===this)closeAdminModal()">
    <div class="modal-panel" role="dialog" aria-modal="true" aria-labelledby="adminModalTitle">
      <div class="modal-header">
        <h3 id="adminModalTitle">详情</h3>
        <button type="button" class="secondary modal-close" onclick="closeAdminModal()">关闭</button>
      </div>
      <div id="adminModalBody"></div>
      <div id="adminModalActions" class="modal-actions"></div>
      <div id="adminModalMsg" class="hint" style="margin-top:8px"></div>
    </div>
  </div>
  <script>
    let authenticated = {auth_state};
    const voiceTestMode = {voice_test_mode};
    const platformLlmDefaults = {json.dumps(platform_llm, ensure_ascii=False)};
    let users = [];
    let agents = [];
    let devices = [];
    let deviceSecretEncryptionConfigured = true;
    let mbtiTypes = [];
    let bindUsersPage = [];
    let bindDevicesPage = [];
    let bindings = [];
    let lastBatch = [];
    let selectedUserId = '';
    let selectedDeviceId = '';
    let adminModalCopyPayload = '';
    const listState = {{
      devices: {{cursor:'', nextCursor:'', stack:[], q:'', limit:20}},
      users: {{cursor:'', nextCursor:'', stack:[], q:'', limit:20}},
      agents: {{cursor:'', nextCursor:'', stack:[], q:'', limit:20}},
      bindings: {{cursor:'', nextCursor:'', stack:[], q:'', limit:20}},
      bindUsers: {{cursor:'', nextCursor:'', stack:[], q:'', limit:20}},
      bindDevices: {{cursor:'', nextCursor:'', stack:[], q:'', limit:20}},
    }};
    const headers = () => ({{'Content-Type': 'application/json'}});
    function $(id) {{ return document.getElementById(id); }}
    function esc(value) {{
      return String(value ?? '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
    }}
    function jsQuote(value) {{
      return String(value ?? '').replace(/\\\\/g, '\\\\\\\\').replace(/'/g, "\\\\'").replace(/\\n/g, '\\\\n');
    }}
    function truncateId(text, head = 10, tail = 6) {{
      const s = String(text ?? '');
      if (s.length <= head + tail + 3) return s;
      return s.slice(0, head) + '…' + s.slice(-tail);
    }}
    function closeAdminModal() {{
      const el = $('adminModal');
      if (!el) return;
      el.classList.remove('open');
      $('adminModalBody').innerHTML = '';
      $('adminModalActions').innerHTML = '';
      $('adminModalMsg').textContent = '';
      adminModalCopyPayload = '';
    }}
    async function copyAdminText(text) {{
      const msg = $('adminModalMsg');
      try {{
        if (navigator.clipboard && navigator.clipboard.writeText) {{
          await navigator.clipboard.writeText(text);
        }} else {{
          const ta = document.createElement('textarea');
          ta.value = text;
          document.body.appendChild(ta);
          ta.select();
          document.execCommand('copy');
          document.body.removeChild(ta);
        }}
        if (msg) msg.textContent = '已复制到剪贴板';
      }} catch (err) {{
        if (msg) msg.textContent = '复制失败，请手动选择复制';
      }}
    }}
    function openAdminModal({{ title, bodyHtml, copyText, actionsHtml, autoCopy }}) {{
      $('adminModalTitle').textContent = title || '详情';
      $('adminModalBody').innerHTML = bodyHtml || '';
      const actionsEl = $('adminModalActions');
      actionsEl.innerHTML = actionsHtml || '';
      adminModalCopyPayload = copyText || '';
      if (copyText) {{
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.textContent = autoCopy ? '再次复制' : '复制';
        btn.addEventListener('click', () => copyAdminText(copyText));
        actionsEl.appendChild(btn);
      }}
      $('adminModalMsg').textContent = '';
      $('adminModal').classList.add('open');
      if (autoCopy && copyText) copyAdminText(copyText);
    }}
    function openCopyableDetail(title, fullText, autoCopy = true) {{
      openAdminModal({{
        title: title || '详情',
        bodyHtml: `<pre class="modal-body-text">${{esc(fullText)}}</pre>`,
        copyText: fullText,
        autoCopy: autoCopy !== false,
      }});
    }}
    function openIdDetail(label, fullId) {{
      openCopyableDetail(label || 'ID', fullId, true);
    }}
    function llmApiKeyConfigured(llm) {{
      const key = llm && llm.api_key;
      return key === '***' || Boolean(key && String(key).trim());
    }}
    function renderUserLlmStatus(u) {{
      const llm = u.llm_config || {{}};
      const model = llm.model || '未配置';
      const base = llm.base_url || '默认';
      const keyOk = llmApiKeyConfigured(llm);
      const keyBadge = keyOk
        ? '<span class="badge">key=已配置</span>'
        : '<span class="badge warn">key=未配置</span>';
      const wxWarn = (String(u.user_id || '').startsWith('wx_') && !keyOk)
        ? '<span class="badge warn">微信用户需配 LLM</span>' : '';
      return `<div class="meta-line">${{esc(model)}} · base=${{esc(base)}}</div><div class="badge-row">${{keyBadge}}${{wxWarn}}</div>`;
    }}
    function openUserLlmModal(userId) {{
      const u = users.find(item => item.user_id === userId);
      if (!u) return;
      const llm = u.llm_config || {{}};
      const modelVal = llm.model || platformLlmDefaults.model || '';
      const baseVal = llm.base_url || platformLlmDefaults.base_url || '';
      const keyHint = llmApiKeyConfigured(llm) ? '已配置，留空则不修改' : '未配置，请填写';
      const q = jsQuote(userId);
      openAdminModal({{
        title: `配置 LLM · ${{userId}}`,
        bodyHtml: `<div class="llm-form">
          <label><span class="hint">模型</span><input id="llmModalModel" value="${{esc(modelVal)}}" placeholder="${{esc(platformLlmDefaults.model || '')}}" /></label>
          <label><span class="hint">Base URL</span><input id="llmModalBaseUrl" type="url" value="${{esc(baseVal)}}" placeholder="${{esc(platformLlmDefaults.base_url || '')}}" /></label>
          <label><span class="hint">API Key</span><input id="llmModalApiKey" type="password" placeholder="${{esc(keyHint)}}" autocomplete="off" /></label>
        </div>`,
        actionsHtml: `<button type="button" class="secondary" onclick="closeAdminModal()">取消</button><button type="button" onclick="saveUserLlmModal('${{q}}')">保存</button>`,
      }});
    }}
    async function saveUserLlmModal(userId) {{
      const u = users.find(item => item.user_id === userId);
      if (!u) return;
      const llm = {{
        model: ($('llmModalModel') && $('llmModalModel').value) || '',
        base_url: ($('llmModalBaseUrl') && $('llmModalBaseUrl').value) || '',
        api_key: ($('llmModalApiKey') && $('llmModalApiKey').value) || '',
      }};
      const payload = {{
        user_id: userId,
        token_quota_total: Number(u.token_quota_total || 0),
        token_quota_used: Number(u.token_quota_used || 0),
        audio_quota_mb: Number(u.audio_quota_mb || 512),
        enabled: u.enabled !== false,
        llm_config: llm,
      }};
      const res = await fetch('/admin/api/users', {{method:'POST', headers:headers(), body:JSON.stringify(payload), credentials:'same-origin'}});
      const data = await res.json();
      if (!res.ok || data.error) {{
        $('adminModalMsg').textContent = data.error || '保存失败';
        return;
      }}
      closeAdminModal();
      await loadUsers();
    }}
    function renderClipCell(fullText, metaHtml, label, stopPropagation) {{
      const lid = label || 'ID';
      const q = jsQuote(fullText);
      const lq = jsQuote(lid);
      const stop = stopPropagation ? 'event.stopPropagation();' : '';
      const meta = metaHtml ? `<div class="meta">${{metaHtml}}</div>` : '';
      return `<div class="cell-clip" role="button" tabindex="0" title="${{esc(fullText)}}"
        onclick="${{stop}}openIdDetail('${{lq}}', '${{q}}')"
        onkeydown="if(event.key==='Enter'){{ event.preventDefault(); ${{stop}}openIdDetail('${{lq}}', '${{q}}'); }}">
        <strong>${{esc(truncateId(fullText))}}</strong>${{meta}}
      </div>`;
    }}
    function renderEncryptionBanner() {{
      const banner = $('batchEncryptionBanner');
      if (banner) banner.style.display = deviceSecretEncryptionConfigured ? 'none' : 'block';
    }}
    function renderSecretCell(d) {{
      const id = d.device_id;
      const q = jsQuote(id);
      const masked = d.device_secret_masked || '';
      const display = masked || (d.device_secret_retrievable ? '已配置' : '未入库');
      const hintMeta = d.device_secret_retrievable
        ? '点击查看并复制'
        : (deviceSecretEncryptionConfigured ? '需重新制码后查看' : '需先配置加密密钥并重新制码');
      return `<div class="cell-clip cell-secret" role="button" tabindex="0" title="${{esc(id)}} 密钥"
        onclick="revealDeviceSecret('${{q}}')"
        onkeydown="if(event.key==='Enter'){{ event.preventDefault(); revealDeviceSecret('${{q}}'); }}">
        <strong>${{esc(truncateId(display))}}</strong>
        <div class="meta">${{esc(hintMeta)}}</div>
      </div>`;
    }}
    async function copyClaimCode(text) {{
      const value = String(text || '').trim();
      if (!value) {{ alert('无外壳码'); return; }}
      try {{
        if (navigator.clipboard && navigator.clipboard.writeText) {{
          await navigator.clipboard.writeText(value);
        }} else {{
          const ta = document.createElement('textarea');
          ta.value = value;
          document.body.appendChild(ta);
          ta.select();
          document.execCommand('copy');
          document.body.removeChild(ta);
        }}
        alert('外壳码已复制');
      }} catch (err) {{
        alert('复制失败，请手动选择复制');
      }}
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
      for (const id of ['devices','users','agents','paymentPlans','bindings','adapters']) $(''+id).style.display = id === name ? 'grid' : 'none';
      for (const id of ['tabDevices','tabUsers','tabAgents','tabPaymentPlans','tabBindings','tabAdapters']) $(id).classList.remove('active');
      $('tab' + name[0].toUpperCase() + name.slice(1)).classList.add('active');
      if (name === 'paymentPlans' && authenticated) loadPaymentPlans();
      if (name === 'bindings' && authenticated) {{
        loadBindUsers();
        loadBindDevices();
      }}
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
      if (name === 'agents') return loadAgents();
      if (name === 'bindUsers') return loadBindUsers();
      if (name === 'bindDevices') return loadBindDevices();
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
    async function loadAll() {{
      await Promise.all([
        loadMbtiTypes(), loadDevices(), loadUsers(), loadAgents(), loadPaymentPlans(), loadBindings(), loadAdapters(),
        loadBindUsers(), loadBindDevices(),
      ]);
    }}
    async function loadMbtiTypes() {{
      const res = await fetch('/admin/api/mbti/types', {{headers: headers(), credentials: 'same-origin'}});
      const data = await res.json();
      if (res.ok) mbtiTypes = data.items || [];
    }}
    function mbtiOptionsHtml(selected) {{
      const items = mbtiTypes.length
        ? mbtiTypes
        : (selected ? [{{type: selected, tagline: ''}}] : []);
      let html = '<option value="">—</option>';
      for (const item of items) {{
        const sel = item.type === selected ? ' selected' : '';
        html += `<option value="${{esc(item.type)}}"${{sel}}>${{esc(item.type)}}</option>`;
      }}
      return html;
    }}
    function agentOptionsHtml(selected) {{
      const opts = agents.map(a => `<option value="${{esc(a.agent_id)}}" ${{a.agent_id === selected ? 'selected' : ''}}>${{esc(a.display_name || a.agent_id)}} (${{esc(a.agent_id)}})</option>`).join('');
      return `<option value="">— 默认 shuxin —</option>` + opts;
    }}
    async function applyVolcTtsDefaults() {{
      if (!confirm('将所有未删除设备的 TTS 设为火山复刻 (volcengine-clone)？')) return;
      const res = await fetch('/admin/api/devices/apply-tts-defaults', {{method:'POST', headers:headers(), credentials:'same-origin'}});
      const data = await res.json();
      if (!res.ok || data.error) {{
        openAdminModal({{title: '应用 TTS 失败', bodyHtml: `<p class="hint">${{esc(data.error || '操作失败')}}</p>`}});
        return;
      }}
      openAdminModal({{
        title: '已应用火山 TTS',
        bodyHtml: `<p class="hint">已更新 ${{data.updated_count ?? 0}} 台设备为 volcengine-clone。</p>`,
      }});
      await loadDevices();
    }}
    async function loadAgents() {{
      const data = await (await fetch(listUrl('agents', '/admin/api/agents'))).json();
      agents = data.items || [];
      listState.agents.nextCursor = data.next_cursor || '';
      $('agentList').innerHTML = `<div class="table-row table-head"><div>Agent</div><div>voice_type</div><div>cluster</div><div>soul_path</div><div>操作</div></div>` + agents.map(a => {{
        const q = jsQuote(a.agent_id);
        return `<div class="table-row">
          <div><strong>${{esc(a.display_name || a.agent_id)}}</strong><div class="meta">${{esc(a.agent_id)}}</div></div>
          <input id="voice_${{esc(a.agent_id)}}" value="${{esc(a.voice_type || '')}}" placeholder="复刻 ID" />
          <input id="cluster_${{esc(a.agent_id)}}" value="${{esc(a.cluster || 'volcano_icl')}}" />
          <input id="soul_${{esc(a.agent_id)}}" value="${{esc(a.soul_path || '')}}" />
          <div class="toolbar">
            <button class="secondary" onclick="saveAgentRow('${{q}}')">保存</button>
            <button class="secondary" onclick="previewAgent('${{q}}')">试听</button>
            <button class="danger" onclick="deleteAgent('${{q}}')" ${{a.agent_id === 'shuxin' ? 'disabled' : ''}}>删除</button>
          </div>
        </div>`;
      }}).join('');
      renderPager('agents', agents.length);
    }}
    async function loadPaymentPlans() {{
      const settingsRes = await fetch('/admin/api/platform/payment-settings', {{headers: headers(), credentials: 'same-origin'}});
      const settings = await settingsRes.json();
      if (settingsRes.ok && settings.credit_ratio != null) {{
        $('creditRatio').value = settings.credit_ratio;
      }}
      const res = await fetch('/admin/api/payment/plans', {{headers: headers(), credentials: 'same-origin'}});
      const data = await res.json();
      if (!res.ok || data.error) {{
        $('paymentPlanList').innerHTML = `<p class="hint">${{esc(data.error || '加载失败')}}</p>`;
        return;
      }}
      const plans = data.items || [];
      $('paymentPlanList').innerHTML = `<div class="table-row table-head"><div>档位</div><div>支付价(元)</div><div>排序</div><div>启用</div><div>操作</div></div>` + plans.map(p => {{
        const q = jsQuote(p.plan_id || p.id);
        const pid = esc(p.plan_id || p.id);
        const yuan = (Number(p.amount_fen || 0) / 100).toFixed(2);
        return `<div class="table-row">
          <div><strong>${{esc(p.name)}}</strong><div class="meta">${{pid}} · ${{esc(p.description || '')}}</div></div>
          <input id="planAmount_${{pid}}" type="number" min="1" value="${{esc(String(p.amount_fen || 0))}}" />
          <input id="planSort_${{pid}}" type="number" value="${{esc(String(p.sort_order ?? 0))}}" />
          <select id="planEnabled_${{pid}}"><option value="true" ${{p.enabled !== false ? 'selected' : ''}}>启用</option><option value="false" ${{p.enabled === false ? 'selected' : ''}}>停用</option></select>
          <div class="toolbar">
            <input id="planName_${{pid}}" value="${{esc(p.name)}}" placeholder="名称" style="min-width:80px" />
            <button class="secondary" onclick="savePaymentPlanRow('${{q}}')">保存</button>
            <button class="danger" onclick="disablePaymentPlan('${{q}}')" ${{p.enabled === false ? 'disabled' : ''}}>停用</button>
          </div>
        </div>`;
      }}).join('') || '<div class="hint">暂无套餐</div>';
    }}
    async function saveCreditRatio() {{
      const ratio = Number($('creditRatio').value || 0);
      const res = await fetch('/admin/api/platform/payment-settings', {{
        method: 'PATCH',
        headers: headers(),
        credentials: 'same-origin',
        body: JSON.stringify({{credit_ratio: ratio}}),
      }});
      const data = await res.json();
      if (!res.ok || data.error) {{ alert(data.error || '保存失败'); return; }}
      $('creditRatio').value = data.credit_ratio;
      alert('到账比例已保存：' + data.credit_ratio);
    }}
    async function createPaymentPlan() {{
      const payload = {{
        plan_id: $('newPlanId').value.trim(),
        name: $('newPlanName').value.trim(),
        amount_fen: Number($('newPlanAmountFen').value || 0),
        sort_order: Number($('newPlanSort').value || 0),
        description: $('newPlanDesc').value.trim(),
        enabled: true,
      }};
      const res = await fetch('/admin/api/payment/plans', {{method:'POST', headers:headers(), body:JSON.stringify(payload)}});
      const data = await res.json();
      if (!res.ok || data.error) {{ alert(data.error || '创建失败'); return; }}
      $('newPlanId').value = ''; $('newPlanName').value = ''; $('newPlanAmountFen').value = ''; $('newPlanDesc').value = '';
      await loadPaymentPlans();
    }}
    async function savePaymentPlanRow(planId) {{
      const payload = {{
        name: $('planName_' + planId).value.trim(),
        amount_fen: Number($('planAmount_' + planId).value || 0),
        sort_order: Number($('planSort_' + planId).value || 0),
        enabled: $('planEnabled_' + planId).value === 'true',
      }};
      const res = await fetch('/admin/api/payment/plans/' + encodeURIComponent(planId), {{
        method: 'PATCH', headers: headers(), body: JSON.stringify(payload),
      }});
      const data = await res.json();
      if (!res.ok || data.error) alert(data.error || '保存失败');
      else await loadPaymentPlans();
    }}
    async function disablePaymentPlan(planId) {{
      if (!confirm('停用套餐 ' + planId + '？小程序将不再展示。')) return;
      const res = await fetch('/admin/api/payment/plans/' + encodeURIComponent(planId), {{
        method: 'DELETE', headers: headers(),
      }});
      const data = await res.json();
      if (!res.ok || data.error) alert(data.error || '停用失败');
      else await loadPaymentPlans();
    }}
    async function createAgent() {{
      const payload = {{
        agent_id: $('newAgentId').value.trim(),
        display_name: $('newAgentName').value.trim(),
        voice_type: $('newAgentVoice').value.trim(),
        cluster: $('newAgentCluster').value.trim() || 'volcano_icl',
        soul_path: $('newAgentSoul').value.trim(),
      }};
      const res = await fetch('/admin/api/agents', {{method:'POST', headers:headers(), body:JSON.stringify(payload)}});
      const data = await res.json();
      if (!res.ok || data.error) {{ alert(data.error || 'create failed'); return; }}
      $('newAgentId').value = ''; $('newAgentName').value = ''; $('newAgentVoice').value = '';
      await loadAgents();
    }}
    async function saveAgentRow(id) {{
      const payload = {{
        voice_type: $('voice_' + id).value.trim(),
        cluster: $('cluster_' + id).value.trim(),
        soul_path: $('soul_' + id).value.trim(),
      }};
      const res = await fetch('/admin/api/agents/' + encodeURIComponent(id), {{method:'PATCH', headers:headers(), body:JSON.stringify(payload)}});
      const data = await res.json();
      if (!res.ok || data.error) alert(data.error || 'update failed');
      await loadAgents();
    }}
    async function previewAgent(id) {{
      const text = prompt('试听文本', '你好，我是初心') || '你好，我是初心';
      const res = await fetch('/admin/api/tts/preview', {{method:'POST', headers:headers(), body:JSON.stringify({{agent_id:id, text}})}});
      const data = await res.json();
      if (!res.ok || data.error) {{ alert(data.error || 'preview failed'); return; }}
      if (data.audio_url) {{
        const audio = new Audio(data.audio_url + '?t=' + Date.now());
        audio.play().catch(() => alert('播放失败，请检查浏览器自动播放策略'));
      }}
    }}
    async function deleteAgent(id) {{
      if (!confirm('删除 Agent ' + id + '？')) return;
      await fetch('/admin/api/agents/' + encodeURIComponent(id), {{method:'DELETE', headers:headers()}});
      await loadAgents();
    }}
    async function saveUserAgent(userId, agentId) {{
      const res = await fetch('/admin/api/users/' + encodeURIComponent(userId), {{
        method:'PATCH', headers:headers(), body:JSON.stringify({{agent_id: agentId || 'shuxin'}}),
      }});
      const data = await res.json();
      if (!res.ok || data.error) alert(data.error || 'agent update failed');
    }}
    async function saveUserFactoryRole(userId, enabled) {{
      const res = await fetch('/admin/api/users/' + encodeURIComponent(userId), {{
        method:'PATCH',
        headers:headers(),
        body:JSON.stringify({{metadata: {{factory_role: enabled ? 'true' : 'false'}}}}),
        credentials:'same-origin',
      }});
      const data = await res.json();
      if (!res.ok || data.error) {{
        alert(data.error || 'factory_role update failed');
        await loadUsers();
        return;
      }}
      await loadUsers();
    }}
    function deviceStatusBadges(d) {{
      const badges = [];
      badges.push(`<span class="badge ${{d.status.online ? '' : 'off'}}">${{d.status.online ? '在线' : '离线'}}</span>`);
      if (d.bound_user_id) {{
        const uid = d.bound_user_id;
        const q = jsQuote(uid);
        badges.push(`<span class="badge badge-click" role="button" tabindex="0" title="${{esc(uid)}}"
          onclick="event.stopPropagation();openIdDetail('绑定用户', '${{q}}')"
          onkeydown="if(event.key==='Enter'){{ event.stopPropagation(); event.preventDefault(); openIdDetail('绑定用户', '${{q}}'); }}">已绑定 ${{esc(truncateId(uid))}}</span>`);
      }} else badges.push(`<span class="badge warn">未绑定</span>`);
      if (d.claim_status) badges.push(`<span class="badge">认领:${{esc(d.claim_status)}}</span>`);
      if (d.lifecycle_status) badges.push(`<span class="badge">${{esc(d.lifecycle_status)}}</span>`);
      const mbti = (d.metadata && d.metadata.mbti) ? d.metadata.mbti : '';
      const mbtiStatus = (d.metadata && d.metadata.mbti_status)
        ? d.metadata.mbti_status
        : (mbti ? 'locked' : '');
      if (mbti) badges.push(`<span class="badge">${{esc(mbti)}}</span>`);
      if (mbtiStatus) {{
        const warn = mbtiStatus === 'sealed' ? ' warn' : '';
        badges.push(`<span class="badge${{warn}}">mbti:${{esc(mbtiStatus)}}</span>`);
      }}
      if (!d.enabled) badges.push(`<span class="badge off">已停用</span>`);
      return `<div class="badge-row">${{badges.join('')}}</div>`;
    }}
    function showSecretRotateHint(id) {{
      const bodyHtml = deviceSecretEncryptionConfigured
        ? '<p class="hint">该设备制码时未写入可解密密文（多为历史假数据）。请重新批量制码，或通过工程 API <code>POST /admin/api/devices/{{id}}/rotate-secret</code> 轮换密钥后重烧固件。</p>'
        : '<p class="hint">未配置 <code>SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY</code>。请先在 <code>.env</code> 生成 Fernet 密钥、重部署 Docker，再重新批量制码；之后可在本页「查看」密钥。</p>';
      openAdminModal({{ title: '设备密钥', bodyHtml }});
    }}
    async function revealDeviceSecret(id) {{
      const d = devices.find(item => item.device_id === id);
      if (d && !d.device_secret_retrievable) {{
        showSecretRotateHint(id);
        return;
      }}
      const res = await fetch('/admin/api/devices/' + encodeURIComponent(id) + '/secret', {{headers: headers(), credentials: 'same-origin'}});
      const data = await res.json();
      if (!res.ok || data.error) {{
        if (d && !d.device_secret_retrievable) showSecretRotateHint(id);
        else openAdminModal({{title: '设备密钥', bodyHtml: `<p class="hint">${{esc(data.error || '查看失败')}}</p>`}});
        return;
      }}
      openCopyableDetail(`设备 ${{id}} 密钥`, data.device_secret || '', true);
    }}
    async function applyTencentSttDefaults() {{
      if (!confirm('将所有未删除设备的 STT 设为腾讯实时识别 (tencent-realtime)？')) return;
      const res = await fetch('/admin/api/devices/apply-stt-defaults', {{method:'POST', headers:headers(), credentials:'same-origin'}});
      const data = await res.json();
      if (!res.ok || data.error) {{
        openAdminModal({{title: '应用 STT 失败', bodyHtml: `<p class="hint">${{esc(data.error || '操作失败')}}</p>`}});
        return;
      }}
      openAdminModal({{
        title: '已应用腾讯 STT',
        bodyHtml: `<p class="hint">已更新 ${{data.updated_count ?? 0}} 台设备为 tencent-realtime。</p>`,
      }});
      await loadDevices();
    }}
    async function loadDevices() {{
      const data = await (await fetch(listUrl('devices', '/admin/api/devices'))).json();
      devices = data.items || [];
      deviceSecretEncryptionConfigured = data.device_secret_encryption_configured !== false;
      renderEncryptionBanner();
      listState.devices.nextCursor = data.next_cursor || '';
      $('deviceList').innerHTML = devices.length ? devices.map(d => {{
        const sttType = (d.stt_config && d.stt_config.type) ? d.stt_config.type : 'local';
        const ttsType = (d.tts_config && d.tts_config.type) ? d.tts_config.type : 'volcengine-clone';
        const mbti = (d.metadata && d.metadata.mbti) ? d.metadata.mbti : '';
        const q = jsQuote(d.device_id);
        const claimCode = d.claim_code || '';
        const claimQ = jsQuote(claimCode);
        const unbindBtn = d.active_binding_id
          ? `<button type="button" class="btn-destructive" onclick="unbindBinding('${{esc(d.active_binding_id)}}', '${{jsQuote(d.bound_user_id || '')}}', '${{q}}')">解绑</button>`
          : '';
        return `<article class="device-card">
        <div class="device-card-head">
          <div class="device-card-id">${{renderClipCell(d.device_id, `auth=${{esc(d.auth_mode || '')}} · stt=${{esc(sttType)}} · tts=${{esc(ttsType)}}`, '设备 ID')}}</div>
          <div>${{deviceStatusBadges(d)}}</div>
        </div>
        <div class="device-card-body">
          <div class="device-card-section">
            <span class="field-label">外壳码</span>
            <div class="readonly-field">
              <code class="claim-code">${{claimCode ? esc(claimCode) : '—'}}</code>
              ${{claimCode ? `<button type="button" class="ghost" onclick="copyClaimCode('${{claimQ}}')">复制</button>` : ''}}
            </div>
          </div>
          <div class="device-card-section">
            <span class="field-label">MBTI</span>
            <div class="device-card-mbti">
              <select id="mbti_${{esc(d.device_id)}}">${{mbtiOptionsHtml(mbti)}}</select>
              <button type="button" class="secondary" onclick="saveDeviceMbti('${{q}}')">保存</button>
            </div>
          </div>
          <div class="device-card-section">
            <span class="field-label">设备密钥</span>
            ${{renderSecretCell(d)}}
          </div>
          <div class="device-card-section device-card-note">
            <span class="field-label">运营备注</span>
            <textarea id="note_${{esc(d.device_id)}}" rows="2" placeholder="售后备注、展厅位置等…">${{esc(d.note || '')}}</textarea>
            <div class="toolbar" style="margin-bottom:0">
              <button type="button" class="secondary" onclick="saveDeviceNote('${{q}}')">保存备注</button>
              <button type="button" class="ghost" onclick="clearDeviceNote('${{q}}')">清空</button>
            </div>
          </div>
        </div>
        ${{unbindBtn ? `<div class="device-card-footer">${{unbindBtn}}</div>` : ''}}
      </article>`;
      }}).join('') : '<div class="hint">暂无设备</div>';
      renderPager('devices', devices.length);
    }}
    async function loadUsers() {{
      await loadAgents();
      const data = await (await fetch(listUrl('users', '/admin/api/users'))).json();
      users = data.items || [];
      listState.users.nextCursor = data.next_cursor || '';
      $('userList').innerHTML = `<div class="table-row users table-head"><div>用户</div><div>Agent</div><div>启用</div><div>工厂QA</div><div>音频MB</div><div>用户余额 / DMX</div><div>LLM 状态</div><div>操作</div></div>` + users.map(u => {{
        const q = jsQuote(u.user_id);
        const agentSel = `<select id="agent_${{esc(u.user_id)}}" onchange="saveUserAgent('${{q}}', this.value)">${{agentOptionsHtml(u.agent_id || 'shuxin')}}</select>`;
        const factoryQa = String((u.metadata && u.metadata.factory_role) || '').toLowerCase() === 'true';
        const qaBadge = factoryQa ? '<span class="badge">QA</span>' : '';
        return `<div class="table-row users">
          <div>${{renderClipCell(u.user_id, `token=${{u.token_configured ? '已配置' : '未配置'}}`, '用户 ID')}} ${{qaBadge}}</div>
          <div>${{agentSel}}</div>
          <input id="userEnabled_${{esc(u.user_id)}}" value="${{u.enabled ? 'true' : 'false'}}" />
          <label class="meta"><input type="checkbox" id="factoryQa_${{esc(u.user_id)}}" ${{factoryQa ? 'checked' : ''}} onchange="saveUserFactoryRole('${{q}}', this.checked)" /> QA</label>
          <input id="audio_${{esc(u.user_id)}}" type="number" min="1" value="${{u.audio_quota_mb || 512}}" />
          <div class="toolbar" style="margin-bottom:0">
            <span id="dmxBalance_${{esc(u.user_id)}}" class="meta">—</span>
            <button type="button" class="ghost" onclick="refreshUserQuota('${{q}}')">刷新</button>
            <button type="button" class="secondary" onclick="openUserTopUpModal('${{q}}')">充值</button>
          </div>
          <div>${{renderUserLlmStatus(u)}}</div>
          <div class="toolbar">
            <button class="secondary" onclick="openUserLlmModal('${{q}}')">配置 LLM</button>
            <button class="secondary" onclick="saveUserRow('${{q}}')">保存</button>
            <button class="danger" onclick="deleteUser('${{q}}')">删除</button>
          </div>
        </div>`;
      }}).join('');
      renderPager('users', users.length);
      await Promise.all(users.map(u => refreshUserQuota(u.user_id)));
    }}
    async function loadBindUsers() {{
      const data = await (await fetch(listUrl('bindUsers', '/admin/api/users'))).json();
      bindUsersPage = data.items || [];
      listState.bindUsers.nextCursor = data.next_cursor || '';
      renderBindingBoard();
      renderPager('bindUsers', bindUsersPage.length);
    }}
    async function loadBindDevices() {{
      const data = await (await fetch(listUrl('bindDevices', '/admin/api/devices'))).json();
      bindDevicesPage = data.items || [];
      listState.bindDevices.nextCursor = data.next_cursor || '';
      renderBindingBoard();
      renderPager('bindDevices', bindDevicesPage.length);
    }}
    async function loadBindings() {{
      const data = await (await fetch(listUrl('bindings', '/admin/api/bindings'))).json();
      bindings = data.items || [];
      listState.bindings.nextCursor = data.next_cursor || '';
      $('bindingList').innerHTML = bindings.length
        ? `<div class="table-row bindings table-head"><div>用户</div><div>设备</div><div>绑定时间</div><div>解绑时间</div><div>在线</div><div>操作</div></div>`
          + bindings.map(b => `<div class="table-row bindings">
          ${{renderClipCell(b.user_id, '', '用户 ID')}}
          ${{renderClipCell(b.device_id, '', '设备 ID')}}
          <div class="meta">${{esc(b.bound_at || '-')}}</div>
          <div class="meta">${{esc(b.unbound_at || '-')}}</div>
          <div><span class="badge ${{b.online ? '' : 'off'}}">${{b.online ? '在线' : '离线'}}</span></div>
          <div><button type="button" class="btn-destructive" onclick="unbindBinding('${{esc(b.binding_id)}}', '${{jsQuote(b.user_id || '')}}', '${{jsQuote(b.device_id || '')}}')">解绑</button></div>
        </div>`).join('')
        : '<div class="hint">暂无 active binding</div>';
      renderPager('bindings', bindings.length);
    }}
    async function loadAdapters() {{
      const data = await (await fetch('/admin/api/adapters')).json();
      $('adapterList').innerHTML = (data.items || []).map(a => `<div class="item"><div><strong>${{a.name}}</strong><div class="meta">${{a.actions.join(', ')}}</div></div></div>`).join('');
    }}
    function selectedBindUser() {{
      return bindUsersPage.find(u => u.user_id === selectedUserId) || null;
    }}
    function renderBindingBoard() {{
      if (!$('bindUserList') || !$('bindDeviceList')) return;
      $('bindUserList').innerHTML = bindUsersPage.length ? bindUsersPage.map(u => {{
        const llm = u.llm_config || {{}};
        const modelHint = llm.model ? ` · ${{esc(llm.model)}}` : '';
        return `
        <div class="item selectable ${{selectedUserId === u.user_id ? 'selected' : ''}}" onclick="selectUser('${{jsQuote(u.user_id)}}')">
          <div>
            ${{renderClipCell(u.user_id, `音频 ${{u.audio_quota_mb}}MB${{modelHint}}`, '用户 ID', true)}}
          </div>
          <span class="badge">${{bindings.filter(b => b.user_id === u.user_id && b.status === 'active').length}} 台</span>
        </div>`;
      }}).join('') : '<div class="hint">暂无用户</div>';
      $('bindDeviceList').innerHTML = bindDevicesPage.length ? bindDevicesPage.map(d => {{
        const boundTo = d.bound_user_id || '';
        const disabled = Boolean(boundTo);
        const statusClass = d.status.online ? 'badge' : 'badge off';
        return `
          <div class="item selectable ${{selectedDeviceId === d.device_id ? 'selected' : ''}} ${{disabled ? 'muted' : ''}}" onclick="${{disabled ? '' : `selectDevice('${{jsQuote(d.device_id)}}')`}}">
            <div>
              ${{renderClipCell(d.device_id, `${{esc(d.note || '')}}`, '设备 ID', true)}}
              ${{boundTo ? renderClipCell(boundTo, '已绑定', '绑定用户', true) : '<div class="meta">未绑定</div>'}}
            </div>
            <span class="${{statusClass}}">${{d.status.online ? '在线' : '离线'}}</span>
          </div>`;
      }}).join('') : '<div class="hint">暂无设备</div>';
      const userLabel = selectedUserId || '未选择用户';
      const deviceLabel = selectedDeviceId || '未选择设备';
      const picked = selectedBindUser();
      const llm = picked && picked.llm_config ? picked.llm_config : {{}};
      const llmHint = picked
        ? ` · LLM: ${{esc(llm.model || '未配置')}} / ${{esc(llm.base_url || '默认')}} / key=${{llm.api_key ? '已配置' : '未配置'}}`
        : '';
      $('bindSummary').textContent = `${{userLabel}} -> ${{deviceLabel}}${{llmHint}}`;
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
      await Promise.all([loadBindings(), loadBindDevices(), loadDevices()]);
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
      $('batchNextHint').textContent = deviceSecretEncryptionConfigured
        ? `下一设备号 ${{data.next_device_id}}；入库后可在设备列表「查看」密钥。`
        : `下一设备号 ${{data.next_device_id}}；请先配置 SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY 再制码。`;
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
    async function saveDeviceNote(id) {{
      const noteEl = $('note_' + id);
      if (!noteEl) {{ alert('备注控件未找到'); return; }}
      const payload = {{note: noteEl.value, enabled: true}};
      const res = await fetch('/admin/api/devices/' + encodeURIComponent(id), {{method:'PATCH', headers:headers(), body:JSON.stringify(payload)}});
      const data = await res.json();
      if (!res.ok || data.error) alert(data.error || '备注保存失败');
      else await loadDevices();
    }}
    async function clearDeviceNote(id) {{
      if (!confirm('确认清空该设备备注？')) return;
      const noteEl = $('note_' + id);
      if (noteEl) noteEl.value = '';
      const payload = {{note: '', enabled: true}};
      const res = await fetch('/admin/api/devices/' + encodeURIComponent(id), {{method:'PATCH', headers:headers(), body:JSON.stringify(payload)}});
      const data = await res.json();
      if (!res.ok || data.error) alert(data.error || '清空失败');
      else await loadDevices();
    }}
    async function saveDeviceMbti(id) {{
      const mbti = $('mbti_' + id).value.trim();
      if (!mbti) {{ alert('请选择 MBTI 类型'); return; }}
      const res = await fetch('/admin/api/devices/' + encodeURIComponent(id) + '/mbti', {{
        method:'PATCH', headers:headers(), body:JSON.stringify({{mbti}}),
      }});
      const data = await res.json();
      if (!res.ok || data.error) alert(data.error || 'mbti update failed');
      await loadDevices();
    }}
    function formatDualBalance(quota) {{
      if (!quota || !quota.configured) return '未配置 DMX';
      if (quota.unlimited_quota) return '无限';
      const display = quota.display_balance_yuan ?? quota.remain_yuan;
      const dmx = quota.dmx_remain_yuan;
      if (display == null && dmx == null) return '查询失败';
      const displayText = display != null ? `${{display}} 元` : '—';
      const dmxText = dmx != null ? `${{dmx}} 元` : '—';
      const suffix = quota.exhausted ? '（已用尽）' : '';
      return `用户 ${{displayText}} / DMX ${{dmxText}}${{suffix}}`;
    }}
    function formatDmxBalance(quota) {{
      return formatDualBalance(quota);
    }}
    async function refreshUserQuota(userId) {{
      const el = $('dmxBalance_' + userId);
      if (el) el.textContent = '查询中…';
      const res = await fetch('/admin/api/users/' + encodeURIComponent(userId) + '/quota', {{headers: headers(), credentials:'same-origin'}});
      const data = await res.json();
      if (!res.ok || data.error) {{
        if (el) el.textContent = data.error || '查询失败';
        return;
      }}
      if (el) el.textContent = formatDmxBalance(data);
    }}
    function openUserTopUpModal(userId) {{
      const q = jsQuote(userId);
      openAdminModal({{
        title: `用户充值 · ${{userId}}`,
        bodyHtml: `<div class="llm-form">
          <label><span class="hint">用户可见金额（元）</span><input id="topUpAmount" type="number" min="0.01" step="0.01" value="10" /></label>
          <label><span class="hint">备注（可选）</span><input id="topUpNote" placeholder="微信收款单号等" /></label>
          <p class="hint">双账本：用户余额 += 填写金额；DMX 实际 += 金额 × 当前到账比例（与微信支付一致）。</p>
        </div>`,
        actionsHtml: `<button type="button" class="secondary" onclick="closeAdminModal()">取消</button><button type="button" onclick="submitUserTopUp('${{q}}')">确认充值</button>`,
      }});
    }}
    async function submitUserTopUp(userId) {{
      const addYuan = Number(($('topUpAmount') && $('topUpAmount').value) || 0);
      const note = ($('topUpNote') && $('topUpNote').value) || '';
      if (!(addYuan > 0)) {{
        $('adminModalMsg').textContent = '请输入大于 0 的充值金额';
        return;
      }}
      const res = await fetch('/admin/api/users/' + encodeURIComponent(userId) + '/quota/top-up', {{
        method: 'POST',
        headers: headers(),
        credentials: 'same-origin',
        body: JSON.stringify({{add_yuan: addYuan, note}}),
      }});
      const data = await res.json();
      if (!res.ok || data.error) {{
        $('adminModalMsg').textContent = data.error || '充值失败';
        return;
      }}
      closeAdminModal();
      await refreshUserQuota(userId);
      alert(`充值成功：+${{addYuan}} 元，当前余额 ${{formatDmxBalance(data)}}`);
    }}
    async function createUser() {{
      const llm = {{
        model: $('newModel').value || platformLlmDefaults.model || '',
        base_url: $('newBaseUrl').value || platformLlmDefaults.base_url || '',
        api_key: $('newApiKey').value,
      }};
      const payload = {{user_id:$('newUserId').value, audio_quota_mb:512, enabled:true, llm_config:llm}};
      const res = await fetch('/admin/api/users', {{method:'POST', headers:headers(), body:JSON.stringify(payload)}});
      const data = await res.json();
      if (!res.ok || data.error) alert(data.error || 'save failed');
      $('newApiKey').value = '';
      await loadUsers();
    }}
    async function saveUserRow(id) {{
      const payload = {{
        user_id:id,
        audio_quota_mb:Number($('audio_' + id).value || 512),
        enabled:$('userEnabled_' + id).value !== 'false',
      }};
      const res = await fetch('/admin/api/users', {{method:'POST', headers:headers(), body:JSON.stringify(payload)}});
      const data = await res.json();
      if (!res.ok || data.error) alert(data.error || 'save failed');
      await loadUsers();
    }}
    async function unbindBinding(bindingId, userId, deviceId) {{
      const uid = userId || '';
      const did = deviceId || '';
      const msg = `确认解绑？\\n用户：${{uid}}\\n设备：${{did}}\\n\\n认领码将恢复为可扫码状态；用户记忆保留。用户刷新小程序后设备将从列表消失。`;
      if (!confirm(msg)) return;
      const res = await fetch('/admin/api/bindings/unbind', {{method:'POST', headers:headers(), body:JSON.stringify({{binding_id: bindingId}})}});
      const data = await res.json();
      if (!res.ok || data.error) {{
        alert(data.error || '解绑失败');
        return;
      }}
      $('bindingMsg').textContent = JSON.stringify(data, null, 2);
      alert('已解绑。用户刷新小程序后设备将从列表消失；可重新扫码绑定。');
      await Promise.all([loadBindings(), loadBindUsers(), loadBindDevices(), loadDevices()]);
    }}
    async function deleteUser(id) {{
      const msg = voiceTestMode
        ? `测试模式：将真删除用户 ${{id}}（解绑设备并清 DB 记忆），确认？`
        : `确认删除用户 ${{id}}？（软删除，同一微信再登录可恢复旧配置）`;
      if (!confirm(msg)) return;
      const res = await fetch('/admin/api/users/' + encodeURIComponent(id), {{method:'DELETE', headers: headers(), credentials:'same-origin'}});
      const data = await res.json().catch(() => ({{}}));
      if (!res.ok || data.error) alert(data.error || '删除失败');
      await loadUsers();
    }}
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
  <title>ChuXin Voice Demo</title>
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
    .hint {{ color: #657080; font-size: 13px; }}
    .llm-warn {{ color: #b8453f; font-weight: 600; }}
    select {{ font: inherit; }}
  </style>
</head>
<body>
  <main>
    <h1>ChuXin 语音测试台</h1>
    <p class="hint" style="margin:0 0 12px;color:#657080;font-size:14px">测试用户 API：在 /admin「用户」Tab 点击<strong>配置 LLM</strong>（微信 wx_ 用户也需单独配置）→ 绑定设备 → 本页 Admin Token → 加载设备 → 连接。</p>
    <div class="toolbar">
      <input id="adminToken" type="password" placeholder="Admin Token" aria-label="admin token" />
      <button id="loadTargets" type="button">加载设备</button>
      <select id="testTarget" aria-label="test target" style="min-width:280px;height:38px;padding:0 8px;border:1px solid #cfd6df;border-radius:6px">
        <option value="">选择用户与设备…</option>
      </select>
    </div>
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
      <div class="row"><div class="label">将使用 LLM</div><div id="llmPreview">-</div></div>
      <div class="row"><div class="label">识别文本</div><div id="stt">-</div></div>
      <div class="row"><div class="label">初心回复</div><div id="reply">-</div></div>
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
    const llmPreviewEl = document.getElementById('llmPreview');
    const logEl = document.getElementById('log');
    const connectBtn = document.getElementById('connect');
    const recordBtn = document.getElementById('record');
    const loadTargetsBtn = document.getElementById('loadTargets');
    const adminTokenInput = document.getElementById('adminToken');
    const testTargetSelect = document.getElementById('testTarget');
    const deviceInput = document.getElementById('deviceCode');
    const secretInput = document.getElementById('deviceSecret');
    const clientInput = document.getElementById('clientId');
    let demoTargets = [];
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

    const savedAdminToken = localStorage.getItem('shuxin_voice_demo_admin') || '';
    if (savedAdminToken) adminTokenInput.value = savedAdminToken;

    function formatLlmTarget(item) {{
      if (!item) return '-';
      const model = item.llm_model || '未配置';
      const base = item.llm_base_url || '默认';
      const key = item.llm_api_key_configured ? '已配置' : '未配置';
      return `${{item.user_id}} · model=${{model}} · base=${{base}} · key=${{key}}`;
    }}
    function renderLlmPreview(item) {{
      if (!item) return '-';
      const base = formatLlmTarget(item);
      if (!item.llm_api_key_configured) {{
        return base + ' — 绑定用户未配置 API Key，请先在 /admin 用户页点击「配置 LLM」';
      }}
      return base;
    }}
    function applyLlmPreviewStyle(item) {{
      if (!item || item.llm_api_key_configured) {{
        llmPreviewEl.className = '';
        llmPreviewEl.style.color = '';
        return;
      }}
      llmPreviewEl.className = 'llm-warn';
      llmPreviewEl.style.color = '#b8453f';
    }}

    async function loadDemoTargets() {{
      const token = adminTokenInput.value.trim();
      if (!token) {{
        log('请先填写 Admin Token');
        return;
      }}
      localStorage.setItem('shuxin_voice_demo_admin', token);
      const res = await fetch('/admin/api/voice-demo/targets', {{
        headers: {{'X-Admin-Token': token}},
      }});
      const data = await res.json();
      if (!res.ok || data.error) {{
        log(data.error || '加载设备失败');
        return;
      }}
      demoTargets = data.items || [];
      testTargetSelect.innerHTML = '<option value="">选择用户与设备…</option>' + demoTargets.map((item, idx) => {{
        const online = item.online ? '在线' : '离线';
        const model = item.llm_model || '未配置';
        const agentLabel = item.agent_display_name || item.agent_id || 'shuxin';
        const voice = item.tts_voice_type ? ` · 音色=${{item.tts_voice_type}}` : '';
        return `<option value="${{idx}}">${{item.user_id}} · ${{item.device_id}} · Agent=${{agentLabel}}${{voice}} · ${{model}} · ${{online}}</option>`;
      }}).join('');
      log(`已加载 ${{demoTargets.length}} 个可测试绑定`);
      if (!demoTargets.length) log('没有 active 绑定或密钥不可读取，请在后台绑定设备并轮换密钥');
    }}

    testTargetSelect.onchange = () => {{
      const item = demoTargets[Number(testTargetSelect.value)];
      if (!item) {{
        llmPreviewEl.textContent = '-';
        applyLlmPreviewStyle(null);
        return;
      }}
      deviceInput.value = item.device_code || item.device_id;
      secretInput.value = item.device_secret || '';
      llmPreviewEl.textContent = renderLlmPreview(item);
      applyLlmPreviewStyle(item);
      log(`已选择 ${{item.user_id}} -> ${{item.device_id}} · Agent=${{item.agent_display_name || item.agent_id || 'shuxin'}}`);
      if (!item.llm_api_key_configured) {{
        log('绑定用户未配置 API Key，请先在 /admin 用户页点击「配置 LLM」后再对话');
      }}
    }};

    loadTargetsBtn.onclick = () => loadDemoTargets();

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
      const picked = demoTargets[Number(testTargetSelect.value)];
      if (picked && !picked.llm_api_key_configured) {{
        log('警告：绑定用户未配置 API Key，对话将出现 connect_error/auth_error 或降级文案');
        llmPreviewEl.textContent = renderLlmPreview(picked);
        applyLlmPreviewStyle(picked);
      }}
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
      ws.onclose = async () => {{
        statusEl.textContent = '已断开';
        recording = false;
        startingRecording = false;
        recordingRequested = false;
        await cleanupAudio();
        restoreReadyState();
        connectBtn.disabled = false;
      }};
      ws.onerror = async () => {{
        log('WebSocket error');
        recording = false;
        startingRecording = false;
        recordingRequested = false;
        await cleanupAudio();
        restoreReadyState();
        connectBtn.disabled = false;
      }};
      ws.onmessage = (event) => {{
        if (typeof event.data !== 'string') {{
          enqueueAudio(event.data);
          return;
        }}
        const msg = JSON.parse(event.data);
        log(JSON.stringify(msg));
        if (msg.type === 'factory_verify') {{
          ws.send(JSON.stringify({{
            type: 'factory_verify_ack',
            verify_id: msg.verify_id,
            status: 'ok'
          }}));
          log('factory_verify_ack sent');
          return;
        }}
        if (msg.type === 'hello' && msg.state === 'ok') {{
          boundUserEl.textContent = `${{msg.user_id || '-'}} / ${{msg.device_id || '-'}}`;
          const picked = demoTargets[Number(testTargetSelect.value)];
          if (picked) {{
            llmPreviewEl.textContent = renderLlmPreview(picked);
            applyLlmPreviewStyle(picked);
          }} else {{
            llmPreviewEl.textContent = '已连接';
            applyLlmPreviewStyle(null);
          }}
        }}
        if (msg.type === 'error') {{
          const errText = String(msg.message || '');
          if (errText.includes('api_key')) {{
            log('LLM 未配置：请在 /admin 用户页为该绑定用户点击「配置 LLM」填写 API Key');
          }}
          recording = false;
          startingRecording = false;
          recordingRequested = false;
          restoreReadyState();
        }}
        if (msg.type === 'agent' && msg.state === 'error' && msg.error_kind) {{
          const picked = demoTargets[Number(testTargetSelect.value)];
          if (picked && !picked.llm_api_key_configured) {{
            log(`Agent 错误 (${{msg.error_kind}})：绑定用户可能未配置 API Key 或 Base URL 不可达`);
          }}
        }}
        if (msg.type === 'stt' && ['partial', 'sentence_final', 'stream_final', 'final'].includes(msg.state)) sttEl.textContent = msg.text || '-';
        if (msg.type === 'agent' && msg.state === 'delta') replyEl.textContent = (replyEl.textContent === '-' ? '' : replyEl.textContent) + (msg.text || '');
        if (msg.type === 'agent' && msg.state === 'reply') replyEl.textContent = msg.text || '-';
        if (msg.type === 'tts' && msg.state === 'stop') {{
          timingEl.textContent = `首字 ${{msg.first_agent_delta_ms || '-'}}ms · 首段语音 ${{msg.first_tts_audio_ms || '-'}}ms · 总耗时 ${{msg.total_elapsed_ms}}ms`;
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
