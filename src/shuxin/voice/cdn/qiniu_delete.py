"""Qiniu Kodo object delete (management API, server-side only)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from shuxin.voice.cdn.qiniu import qiniu_config

logger = logging.getLogger("shuxin.voice.cdn.qiniu_delete")

DEFAULT_RS_HOST = "rs.qiniuapi.com"


def _urlsafe_b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def encoded_entry_uri(bucket: str, key: str) -> str:
    entry = "%s:%s" % (str(bucket).strip(), str(key).lstrip("/"))
    return _urlsafe_b64(entry.encode("utf-8"))


def build_management_authorization(
    *,
    access_key: str,
    secret_key: str,
    method: str,
    path: str,
    host: str,
    content_type: str = "application/x-www-form-urlencoded",
    body: bytes = b"",
) -> str:
    """Build ``Authorization: Qiniu ...`` for Kodo management APIs."""
    signing_str = "%s %s\nHost: %s\nContent-Type: %s\n\n" % (
        method.upper(),
        path,
        host,
        content_type,
    )
    signing_str_bytes = signing_str.encode("utf-8") + (body or b"")
    sign = hmac.new(
        secret_key.encode("utf-8"),
        signing_str_bytes,
        hashlib.sha1,
    ).digest()
    return "Qiniu %s:%s" % (access_key, _urlsafe_b64(sign))


def delete_object(key: str, *, timeout_seconds: float = 5.0) -> Dict[str, Any]:
    """Delete a Kodo object by key. Returns ``{ok, status, error?}``.

    Missing object (612) is treated as success (idempotent clear).
    """
    selected = str(key or "").strip().lstrip("/")
    if not selected:
        return {"ok": True, "status": 0, "skipped": True}

    cfg = qiniu_config()
    ak = str(cfg.get("access_key") or "").strip()
    sk = str(cfg.get("secret_key") or "").strip()
    bucket = str(cfg.get("bucket") or "").strip()
    if not ak or not sk or not bucket:
        logger.info("qiniu delete skipped: not configured")
        return {"ok": False, "status": 0, "error": "qiniu_not_configured"}

    host = str(os.environ.get("SHUXIN_QINIU_RS_HOST") or DEFAULT_RS_HOST).strip() or DEFAULT_RS_HOST
    path = "/delete/%s" % encoded_entry_uri(bucket, selected)
    content_type = "application/x-www-form-urlencoded"
    auth = build_management_authorization(
        access_key=ak,
        secret_key=sk,
        method="POST",
        path=path,
        host=host,
        content_type=content_type,
    )
    url = "https://%s%s" % (host, path)
    req = urllib.request.Request(
        url,
        data=b"",
        method="POST",
        headers={
            "Host": host,
            "Content-Type": content_type,
            "Authorization": auth,
            "User-Agent": "shuxin-voice/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=float(timeout_seconds)) as resp:
            status = int(getattr(resp, "status", 200) or 200)
            return {"ok": True, "status": status}
    except urllib.error.HTTPError as exc:
        status = int(exc.code or 0)
        # 612: no such file — treat as already gone
        if status in (200, 612):
            return {"ok": True, "status": status}
        logger.info("qiniu delete HTTP %s for key=%s", status, selected)
        return {"ok": False, "status": status, "error": "http_%s" % status}
    except Exception as exc:
        logger.info("qiniu delete failed: %s", exc)
        return {"ok": False, "status": 0, "error": str(exc)}


def delete_user_avatar(user_id: str) -> Dict[str, Any]:
    """Best-effort delete of the fixed ugc_avatar key for a user."""
    from shuxin.voice.cdn.purposes import resolve_key

    uid = str(user_id or "").strip()
    if not uid:
        return {"ok": True, "skipped": True}
    try:
        key = resolve_key("ugc_avatar", user_id=uid)
    except ValueError:
        return {"ok": False, "error": "bad_user_id"}
    return delete_object(key)
