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


@router.post("/api/users/me/age-consent")
async def user_age_consent(request: Request, repo=Depends(get_repo)):
    try:
        payload = await request.json()
        session_token = str(payload.get("session_token") or "")
        if not session_token:
            raise ValueError("session_token is required")
        return JSONResponse(
            await repo.set_user_age_consent_by_session(
                session_token,
                version=str(payload.get("version") or ""),
            )
        )
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=401)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        logger.exception("age consent failed")
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/api/users/upload-token")
async def user_upload_token(request: Request, repo=Depends(get_repo)):
    """Issue Qiniu upload token for the logged-in user's ugc_avatar only."""
    try:
        payload = await request.json()
        session_token = str(payload.get("session_token") or "")
        purpose = str(payload.get("purpose") or "ugc_avatar").strip()
        if not session_token:
            raise ValueError("session_token is required")
        if purpose != "ugc_avatar":
            return JSONResponse(
                {"error": "purpose %s is not allowed on user upload token API" % purpose},
                status_code=400,
            )
        profile = await repo.get_user_profile_by_session(session_token)
        user_id = str(profile.get("user_id") or "")
        from shuxin.voice.cdn.token_signer import issue_upload_token

        out = issue_upload_token(purpose="ugc_avatar", user_id=user_id)
        return JSONResponse(out)
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=401)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        logger.exception("user upload token failed")
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/api/users/profile")
async def user_profile_update(request: Request, repo=Depends(get_repo)):
    try:
        payload = await request.json()
        session_token = str(payload.get("session_token") or "")
        if not session_token:
            raise ValueError("session_token is required")
        kwargs = {}
        if "nickname" in payload:
            kwargs["nickname"] = payload.get("nickname")
        if "avatar_key" in payload:
            kwargs["avatar_key"] = payload.get("avatar_key")
        if not kwargs:
            raise ValueError("nickname or avatar_key is required")
        return JSONResponse(
            await repo.update_user_profile_by_session(session_token, **kwargs)
        )
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=401)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        logger.exception("user profile update failed")
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/api/users/avatar/clear")
async def user_avatar_clear(request: Request, repo=Depends(get_repo)):
    try:
        payload = await request.json()
        session_token = str(payload.get("session_token") or "")
        if not session_token:
            raise ValueError("session_token is required")
        return JSONResponse(await repo.clear_user_avatar_by_session(session_token))
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=401)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        logger.exception("user avatar clear failed")
        return JSONResponse({"error": str(exc)}, status_code=500)


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
