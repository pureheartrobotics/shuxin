"""账号级年满 18 岁确认（与登录服务协议分离）。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

AGE_CONSENT_VERSION = "2026-07-28"
AGE_CONSENT_META_KEY = "age_consent"


def age_consent_ok(meta: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(meta, dict):
        return False
    raw = meta.get(AGE_CONSENT_META_KEY)
    if not isinstance(raw, dict):
        return False
    return str(raw.get("version") or "").strip() == AGE_CONSENT_VERSION


def build_age_consent_record(*, version: str = AGE_CONSENT_VERSION) -> Dict[str, Any]:
    return {
        "version": str(version or AGE_CONSENT_VERSION).strip() or AGE_CONSENT_VERSION,
        "agreed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
