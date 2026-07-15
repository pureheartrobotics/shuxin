#!/usr/bin/env python3
"""Bind a physical device as RTC lab callee (bob / 小明).

Default device_code matches firmware factory header SX-000003.

  export SHUXIN_ADMIN_TOKEN=...
  # Prefer matching existing firmware secret (no rotate):
  python3 scripts/bind_rtc_lab_hardware_callee.py --base http://127.0.0.1:8765

  # If reveal empty / auth fails, rotate and write secret into factory header:
  python3 scripts/bind_rtc_lab_hardware_callee.py --base http://127.0.0.1:8765 --rotate --sync-firmware-header
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional


CALLEE_USER = "rtc_lab_callee"
CALLEE_HANDLE = "bob"
CALLER_USER = "rtc_lab_caller"
CALLER_HANDLE = "alice"
CONTACT_NAME = "小明"
DEFAULT_DEVICE = "SX-000003"

FW_HEADER = Path(
    "/mnt/e/work/work/shuxin/yingjian/SHUXIN-esp32-2.0.3-button/main/shuxin_factory_config.h"
)


def _default_stt_config() -> Dict[str, Any]:
    return {
        "type": "tencent-realtime",
        "appid": os.environ.get("TENCENT_ASR_APPID", ""),
        "model": "16k_zh",
        "output_dir": "outputs",
    }


def _default_tts_config() -> Dict[str, Any]:
    return {
        "type": "volcengine-clone",
        "profile_id": "shuxin",
        "encoding": "mp3",
        "output_dir": "outputs",
    }


def _request(
    base: str,
    method: str,
    path: str,
    token: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=body,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-Admin-Token": token,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc


def _llm_config_from_env() -> Dict[str, str]:
    model = (os.environ.get("DEMO_LLM_MODEL") or "deepseek-chat").strip()
    base_url = (os.environ.get("DEMO_LLM_BASE_URL") or "").strip()
    api_key = (os.environ.get("DEMO_LLM_API_KEY") or "").strip()
    cfg: Dict[str, str] = {"model": model}
    if base_url:
        cfg["base_url"] = base_url
    if api_key:
        cfg["api_key"] = api_key
    return cfg


def _sync_firmware_header(device_id: str, secret: str) -> None:
    if not FW_HEADER.is_file():
        print(f"WARN: firmware header missing: {FW_HEADER}", file=sys.stderr)
        return
    text = FW_HEADER.read_text(encoding="utf-8")
    text2 = re.sub(
        r'#define SHUXIN_DEVICE_CODE\s+".*"',
        f'#define SHUXIN_DEVICE_CODE "{device_id}"',
        text,
        count=1,
    )
    text2 = re.sub(
        r'#define SHUXIN_DEVICE_SECRET\s+".*"',
        f'#define SHUXIN_DEVICE_SECRET "{secret}"',
        text2,
        count=1,
    )
    if text2 != text:
        FW_HEADER.write_text(text2, encoding="utf-8")
        print(f"Updated {FW_HEADER} device_code/secret (re-flash; clear NVS if stale)")
    else:
        print("Firmware header already matches")


def main() -> int:
    parser = argparse.ArgumentParser(description="Bind hardware as RTC lab callee")
    parser.add_argument("--base", default=os.environ.get("SHUXIN_VOICE_BASE", "http://127.0.0.1:8765"))
    parser.add_argument("--token", default=os.environ.get("SHUXIN_ADMIN_TOKEN", ""))
    parser.add_argument("--device-id", default=DEFAULT_DEVICE)
    parser.add_argument("--rotate", action="store_true", help="Always rotate secret")
    parser.add_argument(
        "--sync-firmware-header",
        action="store_true",
        help="Write device_id/secret into shuxin_factory_config.h",
    )
    args = parser.parse_args()
    if not args.token:
        print("SHUXIN_ADMIN_TOKEN / --token required", file=sys.stderr)
        return 2

    llm = _llm_config_from_env()
    print("== ensure callee user ==")
    _request(
        args.base,
        "POST",
        "/admin/api/users",
        args.token,
        {
            "user_id": CALLEE_USER,
            "enabled": True,
            "llm_config": llm,
            "metadata": {"lab": "rtc_call", "note": "hardware callee"},
            "quota_note": "rtc lab peer",
        },
    )
    print(f"  user {CALLEE_USER} ok")

    print("== upsert hardware device ==")
    _request(
        args.base,
        "POST",
        "/admin/api/devices",
        args.token,
        {
            "device_id": args.device_id,
            "enabled": True,
            "note": "RTC lab hardware callee",
            "metadata": {"lab": "rtc_call", "role": "callee"},
            "stt_config": _default_stt_config(),
            "tts_config": _default_tts_config(),
        },
    )
    print(f"  device {args.device_id} upserted")

    secret = ""
    if not args.rotate:
        try:
            revealed = _request(
                args.base, "GET", f"/admin/api/devices/{args.device_id}/secret", args.token
            )
            secret = str(revealed.get("device_secret") or "")
            print(f"  revealed secret_len={len(secret)}")
        except Exception as exc:
            print(f"  reveal failed ({exc}); will rotate")

    if args.rotate or not secret:
        print("== rotate secret ==")
        rotated = _request(
            args.base,
            "POST",
            f"/admin/api/devices/{args.device_id}/rotate-secret",
            args.token,
            {},
        )
        secret = str(rotated.get("device_secret") or "")
        print(f"  rotated secret_len={len(secret)}")

    print("== bind to rtc_lab_callee ==")
    bound = _request(
        args.base,
        "POST",
        "/admin/api/bindings",
        args.token,
        {"user_id": CALLEE_USER, "device_id": args.device_id},
    )
    print(f"  {json.dumps(bound, ensure_ascii=False)[:200]}")

    print("== seed handles (memory) ==")
    seeded = _request(
        args.base,
        "POST",
        "/admin/api/call-test/seed",
        args.token,
        {
            "handles": [
                {"user_id": CALLER_USER, "handle": CALLER_HANDLE},
                {"user_id": CALLEE_USER, "handle": CALLEE_HANDLE},
            ],
            "contacts": [
                {
                    "owner_user_id": CALLER_USER,
                    "nickname": CONTACT_NAME,
                    "target_handle": CALLEE_HANDLE,
                }
            ],
        },
    )
    print(f"  {seeded}")

    if args.sync_firmware_header and secret:
        _sync_firmware_header(args.device_id, secret)

    print("\n== next ==")
    print(f"1) Firmware WS must be ws://192.168.10.2:8765/ws/voice")
    print(f"2) device_code={args.device_id} secret must match NVS or factory header")
    print(f"3) Browser: connect SX-RTC-CALLER, say 打电话给小明")
    print(f"4) Board: local ringtone -> press LISTEN to accept")
    if secret:
        print(f"\ndevice_secret (keep private): {secret}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
