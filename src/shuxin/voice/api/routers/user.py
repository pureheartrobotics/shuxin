from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from shuxin.voice.integrations.barcode import decode_barcode_image_base64
from shuxin.voice.integrations.dmx_client import QUOTA_EXHAUSTED_MESSAGE
from shuxin.voice.api import voice_session_registry as vsr
from shuxin.voice.persistence.users import DEFAULT_USER_ID
from shuxin.voice.api.routers.deps import get_repo

logger = logging.getLogger("shuxin.voice.api.routers.user")

router = APIRouter(tags=["User"])


@router.post("/api/barcodes/decode")
async def decode_barcode(request: Request):
    payload = await request.json()
    return JSONResponse(
        decode_barcode_image_base64(str(payload.get("image_base64") or ""))
    )


@router.post("/api/wechat/login")
async def wechat_login(request: Request, repo=Depends(get_repo)):
    payload = await request.json()
    return JSONResponse(
        await repo.create_wechat_session(wx_code=str(payload.get("wx_code") or ""))
    )


@router.post("/api/users/quota")
async def user_quota(request: Request, repo=Depends(get_repo)):
    payload = await request.json()
    session_token = str(payload.get("session_token") or "")
    if not session_token:
        raise ValueError("session_token is required")
    return JSONResponse(await repo.get_user_quota_by_session(session_token))


@router.post("/api/users/me")
async def user_me(request: Request, repo=Depends(get_repo)):
    payload = await request.json()
    session_token = str(payload.get("session_token") or "")
    if not session_token:
        raise ValueError("session_token is required")
    return JSONResponse(await repo.get_user_profile_by_session(session_token))


@router.get("/api/announcements")
async def get_active_announcements(repo=Depends(get_repo)):
    items = await repo.get_active_announcements()
    return JSONResponse({"items": items})


@router.post("/api/feedbacks")
async def submit_feedback(request: Request, repo=Depends(get_repo)):
    payload = await request.json()
    session_token = str(payload.get("session_token") or "")
    content = str(payload.get("content") or "").strip()
    contact = str(payload.get("contact") or "").strip()
    if not session_token:
        raise ValueError("session_token is required")
    if not content:
        raise ValueError("content is required")
    
    profile = await repo.get_user_profile_by_session(session_token)
    user_id = profile["user_id"]
    
    result = await repo.create_feedback(
        user_id=user_id,
        content=content,
        contact=contact
    )
    return JSONResponse(result)


@router.post("/api/devices/bind")
async def bind_device(request: Request, repo=Depends(get_repo)):
    payload = await request.json()
    session_token = str(payload.get("session_token") or "")
    if session_token:
        quota = await repo.get_user_quota_by_session(session_token)
        if quota.get("exhausted"):
            # Quota exhausted error fallback
            msg = quota.get("message") or QUOTA_EXHAUSTED_MESSAGE
            return JSONResponse({"error": msg, "error_kind": "quota_exhausted"}, status_code=403)
    result = await repo.bind_device(
        wx_code=str(payload.get("wx_code") or ""),
        session_token=session_token,
        claim_code=str(payload.get("claim_code") or ""),
        device_code=str(payload.get("device_code") or ""),
    )
    await vsr.maybe_push_intro_after_bind(result)
    return JSONResponse(result)


@router.post("/api/devices/unbind")
async def unbind_device(request: Request, repo=Depends(get_repo)):
    payload = await request.json()
    session_token = str(payload.get("session_token") or "")
    if session_token:
        return JSONResponse(
            await repo.unbind_device_by_session(
                session_token=session_token,
                device_code=str(payload.get("device_code") or ""),
            )
        )
    wx_code = str(payload.get("wx_code") or "")
    if wx_code:
        return JSONResponse(
            await repo.unbind_device_by_wx_code(
                wx_code=wx_code,
                device_code=str(payload.get("device_code") or ""),
            )
        )
    return JSONResponse(
        await repo.unbind_device(
            user_id=str(payload.get("user_id") or ""),
            device_code=str(payload.get("device_code") or ""),
        )
    )


@router.post("/api/devices/my")
async def my_devices(request: Request, repo=Depends(get_repo)):
    payload = await request.json()
    return JSONResponse(
        await repo.list_my_devices(
            wx_code=str(payload.get("wx_code") or ""),
            session_token=str(payload.get("session_token") or ""),
        )
    )
