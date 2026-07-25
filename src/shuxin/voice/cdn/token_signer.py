"""签发七牛直传 put-policy token（不回显 AK/SK）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict

from shuxin.voice.cdn.purposes import get_purpose, resolve_key
from shuxin.voice.cdn.qiniu import public_url, qiniu_config

DEFAULT_UPLOAD_HOST = "https://up-z2.qiniup.com/"
DEFAULT_EXPIRES_SECONDS = 3600


def _urlsafe_b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _upload_host() -> str:
    raw = str(os.environ.get("SHUXIN_QINIU_UPLOAD_HOST") or DEFAULT_UPLOAD_HOST).strip()
    if not raw:
        raw = DEFAULT_UPLOAD_HOST
    if not raw.endswith("/"):
        raw += "/"
    return raw


def issue_upload_token(
    *,
    purpose: str,
    entity_id: str = "",
    user_id: str = "",
    expires_in: int = DEFAULT_EXPIRES_SECONDS,
) -> Dict[str, Any]:
    """根据 purpose 解析 key 并签发仅能写入该 key 的上传凭证。"""
    spec = get_purpose(purpose)
    key = resolve_key(purpose, entity_id=entity_id, user_id=user_id)
    cfg = qiniu_config()
    ak = str(cfg.get("access_key") or "").strip()
    sk = str(cfg.get("secret_key") or "").strip()
    bucket = str(cfg.get("bucket") or "").strip()
    if not ak or not sk or not bucket:
        raise RuntimeError(
            "Qiniu not configured: set SHUXIN_QINIU_ACCESS_KEY / SECRET_KEY / BUCKET"
        )

    ttl = max(60, int(expires_in or DEFAULT_EXPIRES_SECONDS))
    deadline = int(time.time()) + ttl
    policy = json.dumps(
        {"scope": "%s:%s" % (bucket, key), "deadline": deadline},
        separators=(",", ":"),
    )
    encoded_policy = _urlsafe_b64(policy.encode("utf-8"))
    sign = hmac.new(sk.encode("utf-8"), encoded_policy.encode("utf-8"), hashlib.sha1).digest()
    token = "%s:%s:%s" % (ak, _urlsafe_b64(sign), encoded_policy)

    return {
        "token": token,
        "key": key,
        "upload_url": _upload_host(),
        "cdn_url": public_url(key),
        "expires_in": ttl,
        "purpose": spec.name,
        "max_bytes": int(spec.max_bytes),
        "allowed_mime": sorted(spec.allowed_mime),
    }
