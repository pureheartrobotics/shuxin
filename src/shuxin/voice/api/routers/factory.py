from __future__ import annotations

import os
import logging
from typing import Any
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from shuxin.voice.integrations.barcode import generate_code128_png
from shuxin.voice.api import voice_session_registry as vsr
from shuxin.voice.config.mbti_reveal import build_factory_verify_mbti_payload
from shuxin.voice.api.routers.deps import get_repo, require_admin

logger = logging.getLogger("shuxin.voice.api.routers.factory")

router = APIRouter(tags=["Factory"])

FACTORY_VERIFY_ACK_TIMEOUT_SECONDS = 10.0
DEFAULT_FACTORY_VERIFY_LOG_RETENTION_DAYS = 15


def _factory_verify_log_retention_days() -> int:
    raw = os.environ.get(
        "SHUXIN_FACTORY_VERIFY_LOG_RETENTION_DAYS",
        str(DEFAULT_FACTORY_VERIFY_LOG_RETENTION_DAYS),
    ).strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_FACTORY_VERIFY_LOG_RETENTION_DAYS


@router.post("/api/factory/verify")
async def factory_verify(request: Request, repo=Depends(get_repo)):
    """工厂验收：扫 claim_code → 查 device_id → WS 下发 factory_verify → 等 ack。"""
    import uuid as _uuid
    import asyncio as _asyncio

    payload = await request.json()
    session_token = str(payload.get("session_token") or "")
    claim_code = str(payload.get("claim_code") or "").strip()
    if not claim_code:
        raise ValueError("claim_code is required")

    # 1. 校验操作员权限
    operator_user = await repo.factory_verify_user_has_role(session_token)

    # 2. claim_code → device_id
    try:
        lookup = await repo.factory_verify_lookup(claim_code)
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
            await repo.factory_verify_log(
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

    # 4. 申请并发锁
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

    # 6. 等待 factory_verify_ack
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


@router.get("/api/factory/verify/logs")
async def factory_verify_logs(
    request: Request,
    device_id: str = "",
    limit: int = 50,
    repo=Depends(get_repo),
):
    session_token = request.headers.get("X-Session-Token", "")
    operator_user = await repo.factory_verify_user_has_role(session_token)
    logs = await repo.factory_verify_logs_list(
        operator_user=operator_user,
        device_id=device_id,
        limit=min(max(1, limit), 200),
        retention_days=_factory_verify_log_retention_days(),
    )
    return JSONResponse({"items": logs, "total": len(logs)})


@router.get("/admin/api/factory/verify/summary")
async def admin_factory_verify_summary(
    request: Request,
    device_id: str = "",
    operator_user: str = "",
    limit: int = 200,
    repo=Depends(get_repo),
    _=Depends(require_admin),
):
    logs = await repo.factory_verify_logs_list(
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


@router.post("/api/factory/devices/provision")
async def factory_provision_device(request: Request, repo=Depends(get_repo), _=Depends(require_admin)):
    payload = await request.json()
    return JSONResponse(await repo.provision_device(str(payload.get("device_code") or "")))


@router.post("/admin/api/factory/devices/batch")
async def admin_factory_provision_batch(request: Request, repo=Depends(get_repo), _=Depends(require_admin)):
    payload = await request.json()
    return JSONResponse(await repo.provision_devices_batch(payload))


@router.get("/admin/api/factory/devices/next-sequence")
async def admin_factory_next_sequence(request: Request, device_prefix: str = "SX", repo=Depends(get_repo), _=Depends(require_admin)):
    return JSONResponse(await repo.next_device_sequence(device_prefix))


@router.get("/admin/api/claim-codes/{claim_code}/barcode.png")
async def admin_claim_code_barcode(request: Request, claim_code: str, _=Depends(require_admin)):
    return Response(content=generate_code128_png(claim_code), media_type="image/png")
