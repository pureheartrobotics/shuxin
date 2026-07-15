"""百度纯 RTC Token 签发（AppID + AppKey HmacSHA1）。

参考: https://cloud.baidu.com/doc/RTC/s/Qjxbh7jpu
"""

from __future__ import annotations

import hashlib
import hmac
import os
import random
import time


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def rtc_call_enabled() -> bool:
    return _env("SHUXIN_RTC_CALL_ENABLED", "0") in {"1", "true", "yes", "on"}


def rtc_credentials_configured() -> bool:
    return bool(_env("BAIDU_RTC_APP_ID") and _env("BAIDU_RTC_APP_KEY"))


def get_rtc_app_id() -> str:
    return _env("BAIDU_RTC_APP_ID")


def get_rtc_server_url() -> str:
    return _env("BAIDU_RTC_SERVER_URL", "wss://rtc.exp.bcelive.com/janus")


def get_rtc_token_ttl_seconds() -> int:
    raw = _env("BAIDU_RTC_TOKEN_TTL_SECONDS", "3600")
    try:
        return max(60, int(raw))
    except ValueError:
        return 3600


def generate_rtc_token(
    *,
    app_id: str,
    app_key: str,
    room_name: str,
    user_id: str,
    ttl_seconds: int | None = None,
    now_ts: int | None = None,
    random_hex: str | None = None,
) -> str:
    """生成百度 RTC token（version 004）。"""
    selected_app_id = str(app_id or "").strip()
    selected_app_key = str(app_key or "").strip()
    selected_room = str(room_name or "").strip()
    selected_uid = str(user_id or "").strip()
    if not selected_app_id or not selected_app_key:
        raise ValueError("app_id and app_key are required")
    if not selected_room or not selected_uid:
        raise ValueError("room_name and user_id are required")

    version = "004"
    ts = int(now_ts if now_ts is not None else time.time())
    expect_ts = ts + int(ttl_seconds if ttl_seconds is not None else get_rtc_token_ttl_seconds())
    random_string = (random_hex or format(random.randint(0, 0xFFFFFFFF), "08x"))[:8].zfill(8)

    data = f"ACS{selected_app_id}{ts:010d}{random_string}{selected_room}{selected_uid}{expect_ts:010d}"
    signature = hmac.new(
        selected_app_key.encode("utf-8"),
        data.encode("utf-8"),
        hashlib.sha1,
    ).hexdigest()
    return f"{version}{signature}{ts:010d}{random_string}{expect_ts:010d}"


def generate_rtc_token_from_env(*, room_name: str, user_id: str) -> str:
    app_id = get_rtc_app_id()
    app_key = _env("BAIDU_RTC_APP_KEY")
    if not app_id or not app_key:
        raise RuntimeError("BAIDU_RTC_APP_ID / BAIDU_RTC_APP_KEY not configured")
    return generate_rtc_token(
        app_id=app_id,
        app_key=app_key,
        room_name=room_name,
        user_id=user_id,
    )
