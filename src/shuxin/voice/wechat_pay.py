from __future__ import annotations

import json
import logging
import os
import secrets
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger("shuxin.voice.wechat_pay")


def uses_wechat_pay_public_key() -> bool:
    return bool(_public_key() and _public_key_id())


def wechat_pay_configured() -> bool:
    return all(
        (
            _app_id(),
            _mch_id(),
            _api_v3_key(),
            _cert_serial_no(),
            _notify_url(),
            _private_key_path().is_file(),
        )
    )


def wechat_pay_mock_mode() -> bool:
    return os.environ.get("SHUXIN_WECHAT_MOCK", "").lower() in {"1", "true", "yes"}


def _app_id() -> str:
    return (
        os.environ.get("SHUXIN_WECHAT_APPID")
        or os.environ.get("WECHAT_MINIPROGRAM_APPID")
        or ""
    ).strip()


def _mch_id() -> str:
    return os.environ.get("SHUXIN_WXPAY_MCHID", "").strip()


def _api_v3_key() -> str:
    return os.environ.get("SHUXIN_WXPAY_API_V3_KEY", "").strip()


def _cert_serial_no() -> str:
    return os.environ.get("SHUXIN_WXPAY_CERT_SERIAL_NO", "").strip()


def _notify_url() -> str:
    return os.environ.get("SHUXIN_WXPAY_NOTIFY_URL", "").strip()


def _public_key() -> str:
    path = os.environ.get("SHUXIN_WXPAY_PUBLIC_KEY_PATH", "").strip()
    if path:
        key_path = Path(path)
        if key_path.is_file():
            return key_path.read_text(encoding="utf-8")
    return os.environ.get("SHUXIN_WXPAY_PUBLIC_KEY", "").strip()


def _public_key_id() -> str:
    return os.environ.get("SHUXIN_WXPAY_PUBLIC_KEY_ID", "").strip()


def _private_key_path() -> Path:
    return Path(
        os.environ.get(
            "SHUXIN_WXPAY_PRIVATE_KEY_PATH",
            "/app/data/certs/wxpay_private_key.pem",
        )
    )


def _platform_cert_dir() -> str:
    path = Path(
        os.environ.get(
            "SHUXIN_WXPAY_PLATFORM_CERT_DIR",
            "/app/data/certs/wxpay_platform",
        )
    )
    path.mkdir(parents=True, exist_ok=True)
    selected = str(path)
    return selected if selected.endswith("/") else f"{selected}/"


def _local_platform_cert_count() -> int:
    cert_dir = Path(_platform_cert_dir())
    if not cert_dir.is_dir():
        return 0
    return sum(1 for name in cert_dir.iterdir() if name.suffix.lower() == ".pem")


@lru_cache(maxsize=1)
def _load_private_key() -> str:
    path = _private_key_path()
    if not path.is_file():
        raise RuntimeError(f"WeChat Pay private key not found: {path}")
    return path.read_text(encoding="utf-8")


def _build_client_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "mchid": _mch_id(),
        "private_key": _load_private_key(),
        "cert_serial_no": _cert_serial_no(),
        "apiv3_key": _api_v3_key(),
        "appid": _app_id(),
        "notify_url": _notify_url(),
        "cert_dir": _platform_cert_dir(),
    }
    public_key = _public_key()
    public_key_id = _public_key_id()
    if public_key and public_key_id:
        kwargs["public_key"] = public_key
        kwargs["public_key_id"] = public_key_id
    return kwargs


def _fetch_certificates_raw() -> tuple[int, str]:
    """Call GET /v3/certificates without initializing platform cert cache."""
    import requests
    from wechatpayv3.utils import build_authorization, load_private_key

    private_key = load_private_key(_load_private_key())
    path = "/v3/certificates"
    auth = build_authorization(
        path,
        "GET",
        _mch_id(),
        _cert_serial_no(),
        private_key,
        data=None,
    )
    headers = {
        "Authorization": auth,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    response = requests.get(
        f"https://api.mch.weixin.qq.com{path}",
        headers=headers,
        timeout=15,
    )
    return response.status_code, response.text


def diagnose_platform_certificates() -> dict[str, Any]:
    """Report why platform cert init may fail (does not require WeChatPay init)."""
    detail: dict[str, Any] = {
        "ok": False,
        "local_pem_count": _local_platform_cert_count(),
        "platform_cert_dir": _platform_cert_dir(),
        "uses_public_key_mode": uses_wechat_pay_public_key(),
    }
    if uses_wechat_pay_public_key():
        detail["ok"] = True
        detail["hint"] = (
            "WeChat Pay public key mode is configured; platform certificate download "
            "is not required."
        )
        return detail

    missing = [
        name
        for name, value in (
            ("app_id", _app_id()),
            ("mchid", _mch_id()),
            ("api_v3_key", _api_v3_key()),
            ("cert_serial_no", _cert_serial_no()),
            ("notify_url", _notify_url()),
        )
        if not value
    ]
    if missing:
        detail["error"] = f"WeChat Pay env incomplete: {', '.join(missing)}"
        return detail
    if not _private_key_path().is_file():
        detail["error"] = f"Private key not found: {_private_key_path()}"
        return detail

    try:
        code, message = _fetch_certificates_raw()
    except Exception as exc:
        detail["error"] = f"GET /v3/certificates request failed: {exc}"
        return detail

    detail["certificates_http_status"] = code
    detail["certificates_body_preview"] = str(message)[:500]

    if code != 200:
        body = message or ""
        if "RESOURCE_NOT_EXISTS" in body or "微信支付公钥" in body:
            detail["error"] = (
                "Merchant account uses WeChat Pay public key mode (no platform cert). "
                "Download public key from pay.weixin.qq.com -> 账户中心 -> API安全, "
                "then set SHUXIN_WXPAY_PUBLIC_KEY_PATH and SHUXIN_WXPAY_PUBLIC_KEY_ID."
            )
        else:
            detail["error"] = (
                "GET /v3/certificates failed — check mchid, cert serial, private key, "
                "and APIv3 key"
            )
        return detail

    try:
        payload = json.loads(message or "{}")
    except json.JSONDecodeError:
        detail["error"] = "Invalid JSON from /v3/certificates"
        return detail

    data = payload.get("data") or []
    detail["certificate_entries"] = len(data)
    if not data:
        detail["error"] = "WeChat returned zero platform certificates"
        return detail

    detail["ok"] = True
    detail["hint"] = (
        "Platform certificates are available; SDK should auto-download PEM into "
        "wxpay_platform/ on first init."
    )
    return detail


def _init_client_error_hint() -> str:
    diag = diagnose_platform_certificates()
    parts = ["WeChat Pay client init failed."]
    if diag.get("error"):
        parts.append(str(diag["error"]))
    if diag.get("certificates_http_status"):
        parts.append(f"GET /v3/certificates -> HTTP {diag['certificates_http_status']}.")
    body = str(diag.get("certificates_body_preview") or "")
    if body and "RESOURCE_NOT_EXISTS" not in body:
        parts.append(f"Response: {body[:240]}")
    if diag.get("local_pem_count", 0) == 0 and not uses_wechat_pay_public_key():
        parts.append(
            "Configure SHUXIN_WXPAY_PUBLIC_KEY_PATH + SHUXIN_WXPAY_PUBLIC_KEY_ID "
            "(recommended), or place platform PEM under wxpay_platform/."
        )
    return " ".join(parts)


@lru_cache(maxsize=1)
def _get_client():
    from wechatpayv3 import WeChatPay, WeChatPayType

    try:
        return WeChatPay(
            wechatpay_type=WeChatPayType.MINIPROG,
            **_build_client_kwargs(),
        )
    except Exception as exc:
        hint = _init_client_error_hint()
        logger.exception("WeChat Pay client init failed")
        raise RuntimeError(f"{hint} ({exc})") from exc


def _parse_json_message(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        return message
    if isinstance(message, bytes):
        message = message.decode("utf-8")
    if isinstance(message, str):
        payload = json.loads(message or "{}")
        if isinstance(payload, dict):
            return payload
    raise RuntimeError("WeChat Pay returned unexpected payload")


def build_miniprogram_pay_params(prepay_id: str) -> dict[str, str]:
    client = _get_client()
    time_stamp = str(int(time.time()))
    nonce_str = secrets.token_hex(16)
    package = f"prepay_id={prepay_id}"
    pay_sign = client.sign([_app_id(), time_stamp, nonce_str, package])
    return {
        "timeStamp": time_stamp,
        "nonceStr": nonce_str,
        "package": package,
        "signType": "RSA",
        "paySign": pay_sign,
    }


def create_jsapi_payment(
    *,
    description: str,
    out_trade_no: str,
    amount_fen: int,
    payer_openid: str,
) -> dict[str, Any]:
    if wechat_pay_mock_mode():
        raise RuntimeError("WeChat Pay is disabled while SHUXIN_WECHAT_MOCK=1")
    if not wechat_pay_configured():
        raise RuntimeError("WeChat Pay is not configured")
    if amount_fen <= 0:
        raise ValueError("amount_fen must be positive")
    openid = str(payer_openid or "").strip()
    if not openid:
        raise ValueError("payer_openid is required")

    try:
        client = _get_client()
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(_init_client_error_hint()) from exc

    code, message = client.pay(
        description=description,
        out_trade_no=out_trade_no,
        amount={"total": int(amount_fen), "currency": "CNY"},
        payer={"openid": openid},
    )
    if code != 200:
        raise RuntimeError(f"WeChat Pay prepay failed ({code}): {message}")

    payload = _parse_json_message(message)
    prepay_id = str(payload.get("prepay_id") or "").strip()
    if not prepay_id:
        raise RuntimeError("WeChat Pay prepay did not return prepay_id")
    pay_params = build_miniprogram_pay_params(prepay_id)
    return {
        "prepay_id": prepay_id,
        "pay_params": pay_params,
    }


def parse_payment_notify(headers: dict[str, str], body: bytes) -> dict[str, Any]:
    if not wechat_pay_configured():
        raise RuntimeError("WeChat Pay is not configured")
    client = _get_client()
    payload = client.callback(headers, body)
    if not isinstance(payload, dict):
        raise RuntimeError("WeChat Pay notify verification failed")
    resource = payload.get("resource")
    if isinstance(resource, dict):
        return resource
    return payload


def query_payment_order(out_trade_no: str) -> dict[str, Any]:
    if not wechat_pay_configured():
        raise RuntimeError("WeChat Pay is not configured")
    client = _get_client()
    code, message = client.query(out_trade_no=out_trade_no)
    if code != 200:
        raise RuntimeError(f"WeChat Pay query failed ({code}): {message}")
    return _parse_json_message(message)
