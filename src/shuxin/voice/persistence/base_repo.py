from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from shuxin.voice.persistence.time_display import format_beijing_display, format_beijing_iso
from shuxin.voice.persistence.device_secret_crypto import (
    resolve_stored_device_secret,
    mask_device_secret,
)
from shuxin.voice.persistence.users import validate_user_id, DEFAULT_USER_ID, DEFAULT_AUDIO_QUOTA_MB
from shuxin.voice.config.config import (
    default_device_tts_config,
    default_tencent_stt_config,
    _expand_env,
    _merge_dict,
)

logger = logging.getLogger("shuxin.voice.postgres")

DEVICE_CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")

class BaseRepository:
    def __init__(self, pool, parent=None) -> None:
        self.pool = pool
        self.parent = parent
        self._auth_cache = {}

    def _clear_auth_cache(self, device_id: str | None = None) -> None:
        if device_id:
            self._auth_cache.pop(device_id, None)
        else:
            self._auth_cache.clear()


def _dt(value: Any) -> str:
    return format_beijing_display(value)


def _dt_iso(value: Any) -> str:
    return format_beijing_iso(value)


def _json_obj(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return json.loads(value) if value else {}
    return dict(value)


def _payment_order_item(row: Any) -> dict[str, Any]:
    return {
        "order_id": str(row["order_id"]),
        "out_trade_no": str(row["out_trade_no"]),
        "plan_id": str(row["plan_id"]),
        "plan_name": str(row["plan_name"]),
        "amount_fen": int(row["amount_fen"]),
        "amount_yuan": round(int(row["amount_fen"]) / 100, 2),
        "add_yuan": float(row["add_yuan"]),
        "duration_days": int(row["duration_days"] or 0),
        "status": str(row["status"]),
        "wx_transaction_id": str(row["wx_transaction_id"] or ""),
        "created_at": _dt(row["created_at"]),
        "paid_at": _dt(row["paid_at"]) if row["paid_at"] else "",
    }


def _device_row(row) -> dict[str, Any]:
    auth_mode = str(row["auth_mode"] or "shared_secret")
    secret, secret_hint = resolve_stored_device_secret(
        auth_mode=auth_mode,
        device_secret_encrypted=str(row.get("device_secret_encrypted") or "") or None,
    )
    return {
        "device_id": str(row["device_id"]),
        "device_code": str(row["device_id"]),
        "auth_mode": auth_mode,
        "device_secret_configured": bool(row["device_secret_hash"])
        or auth_mode == "shared_secret",
        "device_secret_masked": mask_device_secret(secret) if secret else "",
        "device_secret_retrievable": bool(secret),
        "device_secret_hint": secret_hint,
        "lifecycle_status": str(row.get("lifecycle_status") or "provisioned"),
        "bound_user_id": str(row.get("bound_user_id") or ""),
        "active_binding_id": str(row.get("active_binding_id") or ""),
        "claim_code": str(row["claim_code"] or ""),
        "claim_status": str(row["claim_status"] or ""),
        "stt_config": _json_obj(row["stt_config"]),
        "tts_config": _json_obj(row["tts_config"]),
        "llm_config": _mask_secrets(_json_obj(row["llm_config"])),
        "enabled": bool(row["enabled"]),
        "note": str(row["note"] or ""),
        "metadata": _json_obj(row["metadata"]),
        "status": {
            "online": bool(row["online"] or False),
            "last_seen": _dt(row["last_seen"]),
            "current_session_id": str(row["current_session_id"] or ""),
            "last_error": str(row["last_error"] or ""),
        },
    }


def _secret_unavailable_message(hint: str) -> str:
    messages = {
        "rotate_to_store_secret": (
            "device secret is not stored for retrieval; rotate secret after setting "
            "SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY"
        ),
        "decrypt_failed": "device secret cannot be decrypted; check SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY",
        "missing_SHUXIN_DEVICE_SHARED_SECRET": "SHUXIN_DEVICE_SHARED_SECRET is not configured",
    }
    return messages.get(hint, "device secret is not available")


def _sanitize_binding_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    from shuxin.voice.config.mbti_reveal import sanitize_device_metadata_for_client

    return sanitize_device_metadata_for_client(metadata)


def _binding_row(row) -> dict[str, Any]:
    return {
        "binding_id": str(row["binding_id"]),
        "user_id": str(row["user_id"]),
        "device_id": str(row["device_id"]),
        "device_code": str(row["device_id"]),
        "status": str(row["status"]),
        "bound_at": _dt(row["bound_at"]),
        "unbound_at": "",
        "device": {
            "enabled": bool(row["enabled"]),
            "note": str(row["note"] or ""),
            "metadata": _sanitize_binding_metadata(_json_obj(row["metadata"])),
        },
        "online": bool(row["online"] or False),
        "last_seen": _dt(row["last_seen"]),
        "current_session_id": str(row["current_session_id"] or ""),
        "last_error": str(row["last_error"] or ""),
    }


def _mask_secrets(value: dict[str, Any]) -> dict[str, Any]:
    masked: dict[str, Any] = {}
    for key, item in value.items():
        lowered = str(key).lower()
        if any(secret_key in lowered for secret_key in ["key", "token", "password", "secret"]):
            masked[key] = "***" if item else ""
        elif isinstance(item, dict):
            masked[key] = _mask_secrets(item)
        else:
            masked[key] = item
    return masked


def _validate_device_code(device_code: str) -> str:
    selected = str(device_code or "").strip()
    if not DEVICE_CODE_PATTERN.fullmatch(selected):
        raise ValueError(
            "device_code must be 1-96 chars and contain only letters, digits, dot, dash, "
            "underscore or colon"
        )
    return selected


def _validate_claim_code(claim_code: str) -> str:
    selected = str(claim_code or "").strip()
    if not DEVICE_CODE_PATTERN.fullmatch(selected):
        raise ValueError(
            "claim_code must be 1-96 chars and contain only letters, digits, dot, dash, "
            "underscore or colon"
        )
    return selected


def _search_pattern(q: str) -> str:
    selected = str(q or "").strip()
    return f"%{selected}%" if selected else ""


def _user_outputs_root(path: Path, user_id: str) -> Path | None:
    for parent in path.parents:
        if parent.name == user_id and parent.parent.name == "users":
            return parent
    return None


def _validate_code_prefix(value: str) -> str:
    selected = str(value or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{0,15}", selected):
        raise ValueError("prefix must be 1-16 uppercase letters, digits or dash")
    return selected


def _make_device_id(prefix: str, sequence: int) -> str:
    return _validate_device_code(f"{prefix}-{sequence:06d}")


def _make_claim_code(prefix: str, batch: str, sequence: int) -> str:
    return _validate_claim_code(f"{prefix}-{batch}-{sequence:06d}")


def _device_sequence(device_id: str) -> int | None:
    match = re.search(r"(\d+)$", device_id)
    return int(match.group(1)) if match else None


def _hash_secret(value: str) -> str:
    pepper = os.environ.get("SHUXIN_SECRET_PEPPER", "")
    return hashlib.sha256(f"{pepper}:{value}".encode("utf-8")).hexdigest()


def _verify_hash(value: str, expected_hash: str | None) -> bool:
    if not expected_hash:
        return False
    return hmac.compare_digest(_hash_secret(value), str(expected_hash))


def _verify_device_secret(row: Any, device_secret: str) -> bool:
    auth_mode = str(row["auth_mode"] or "shared_secret")
    if auth_mode == "shared_secret":
        expected = os.environ.get("SHUXIN_DEVICE_SHARED_SECRET", "")
        return bool(expected) and hmac.compare_digest(device_secret, expected)
    if auth_mode == "per_device_secret":
        return _verify_hash(device_secret, row["device_secret_hash"])
    return False


async def _openid_from_wx_code(wx_code: str) -> str:
    """把小程序 wx.login code 换成 openid；本地开发可显式启用 mock。"""
    code = str(wx_code or "").strip()
    if not code:
        raise PermissionError("wx_code is required")

    if os.environ.get("SHUXIN_WECHAT_MOCK", "").lower() in {"1", "true", "yes"}:
        return validate_user_id(f"wx_{_hash_secret(code)[:24]}")

    app_id = os.environ.get("SHUXIN_WECHAT_APPID") or os.environ.get("WECHAT_MINIPROGRAM_APPID", "")
    app_secret = os.environ.get("SHUXIN_WECHAT_SECRET") or os.environ.get("WECHAT_MINIPROGRAM_SECRET", "")
    if not app_id or not app_secret:
        raise RuntimeError("SHUXIN_WECHAT_APPID and SHUXIN_WECHAT_SECRET are required")

    import httpx

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            "https://api.weixin.qq.com/sns/jscode2session",
            params={
                "appid": app_id,
                "secret": app_secret,
                "js_code": code,
                "grant_type": "authorization_code",
            },
        )
    response.raise_for_status()
    data = response.json()
    if data.get("errcode"):
        raise PermissionError(f"wechat login failed: {data.get('errmsg', data.get('errcode'))}")
    openid = str(data.get("openid") or "")
    if not openid:
        raise PermissionError("wechat login did not return openid")
    return validate_user_id(openid)
