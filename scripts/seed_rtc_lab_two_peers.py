#!/usr/bin/env python3
"""Create two lab users + devices + bindings for RTC / voice-demo call testing.

Idempotent Admin API helper. Example:

  export SHUXIN_ADMIN_TOKEN=...
  python scripts/seed_rtc_lab_two_peers.py --base http://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


CALLER_USER = "rtc_lab_caller"
CALLEE_USER = "rtc_lab_callee"
CALLER_DEVICE = "SX-RTC-CALLER"
CALLEE_DEVICE = "SX-RTC-CALLEE"
CALLER_HANDLE = "alice"
CALLEE_HANDLE = "bob"
CONTACT_NAME = "小明"


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
    model = (
        os.environ.get("DEMO_LLM_MODEL")
        or os.environ.get("SHUXIN_LLM_DEFAULT_MODEL")
        or "deepseek-chat"
    ).strip()
    base_url = (
        os.environ.get("DEMO_LLM_BASE_URL")
        or os.environ.get("SHUXIN_LLM_DEFAULT_BASE_URL")
        or ""
    ).strip()
    api_key = (
        os.environ.get("DEMO_LLM_API_KEY")
        or os.environ.get("SHUXIN_LLM_DEFAULT_API_KEY")
        or ""
    ).strip()
    cfg: Dict[str, str] = {"model": model}
    if base_url:
        cfg["base_url"] = base_url
    if api_key:
        cfg["api_key"] = api_key
    return cfg


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed two RTC lab peers for voice-demo")
    parser.add_argument("--base", default=os.environ.get("SHUXIN_VOICE_BASE", "http://127.0.0.1:8765"))
    parser.add_argument("--token", default=os.environ.get("SHUXIN_ADMIN_TOKEN", ""))
    parser.add_argument(
        "--handles-only",
        action="store_true",
        help="Only reseed in-memory shuxin handles/contacts (no rotate-secret)",
    )
    args = parser.parse_args()
    if not args.token:
        print("SHUXIN_ADMIN_TOKEN / --token required", file=sys.stderr)
        return 2

    peers = [
        (CALLER_USER, CALLER_DEVICE, "RTC lab caller (browser Tab A)"),
        (CALLEE_USER, CALLEE_DEVICE, "RTC lab callee (browser Tab B)"),
    ]

    if args.handles_only:
        print("== seed shuxin handles only ==")
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
        if not seeded.get("ok") or int(seeded.get("handles") or 0) < 2:
            print("ERROR: handle seed failed", file=sys.stderr)
            return 1
        print("\nOK: memory handles restored; reconnect WS if already open, then dial 小明")
        return 0

    llm = _llm_config_from_env()
    if not llm.get("api_key"):
        print(
            "WARNING: DEMO_LLM_API_KEY not set; users may lack LLM key for AI chat",
            file=sys.stderr,
        )

    print("== upsert users ==")
    for user_id, _device_id, note in peers:
        result = _request(
            args.base,
            "POST",
            "/admin/api/users",
            args.token,
            {
                "user_id": user_id,
                "enabled": True,
                "llm_config": llm,
                "metadata": {"lab": "rtc_call", "note": note},
                "quota_note": "rtc lab peer",
            },
        )
        print(f"  user {user_id}: ok llm_key={bool((result.get('llm_config') or {}).get('api_key') if isinstance(result.get('llm_config'), dict) else llm.get('api_key'))}")

    print("== upsert devices ==")
    for _user_id, device_id, note in peers:
        _request(
            args.base,
            "POST",
            "/admin/api/devices",
            args.token,
            {
                "device_id": device_id,
                "enabled": True,
                "note": note,
                "metadata": {"lab": "rtc_call"},
                "stt_config": _default_stt_config(),
                "tts_config": _default_tts_config(),
            },
        )
        print(f"  device {device_id}: upserted")

    print("== rotate secrets ==")
    secrets: Dict[str, str] = {}
    for _user_id, device_id, _note in peers:
        rotated = _request(
            args.base,
            "POST",
            f"/admin/api/devices/{device_id}/rotate-secret",
            args.token,
            {},
        )
        secret = str(rotated.get("device_secret") or "")
        secrets[device_id] = secret
        print(f"  {device_id}: secret_len={len(secret)} auth_mode={rotated.get('auth_mode')}")

    print("== bind devices ==")
    for user_id, device_id, _note in peers:
        bound = _request(
            args.base,
            "POST",
            "/admin/api/bindings",
            args.token,
            {"user_id": user_id, "device_id": device_id},
        )
        print(f"  bind {user_id} <-> {device_id}: {json.dumps(bound, ensure_ascii=False)[:160]}")

    print("== seed shuxin handles ==")
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

    print("== voice-demo targets ==")
    targets = _request(args.base, "GET", "/admin/api/voice-demo/targets", args.token)
    items = targets.get("items") or []
    lab_items = [
        item
        for item in items
        if str(item.get("device_id") or "") in {CALLER_DEVICE, CALLEE_DEVICE}
    ]
    print(f"  total_targets={len(items)} lab_targets={len(lab_items)}")
    for item in lab_items:
        print(
            f"  - {item.get('user_id')} · {item.get('device_id')} · "
            f"secret_hint={item.get('secret_hint')} · "
            f"llm_key={item.get('llm_api_key_configured')}"
        )

    if len(lab_items) < 2:
        print("ERROR: lab targets missing from voice-demo list", file=sys.stderr)
        return 1

    print("\n== how to test ==")
    print("1) Open two browser windows at http://localhost:8765/voice-demo")
    print("2) Admin Token -> Load devices")
    print(f"3) Window A: select {CALLER_USER} · {CALLER_DEVICE} -> Connect")
    print(f"4) Window B: select {CALLEE_USER} · {CALLEE_DEVICE} -> Connect")
    print(f"5) On A, after STT or via server tools, dial nickname '{CONTACT_NAME}' (maps to {CALLEE_HANDLE})")
    print("   Or ensure SHUXIN_RTC_CALL_ENABLED=1 and say: 打电话给小明")
    print(f"6) Window B should show incoming call UI -> Accept")
    print("7) Both sides need mic permission; use headphones on one PC to avoid howl")
    print("8) Log should show 'BRTC joined' not stub")
    if secrets.get(CALLER_DEVICE):
        print(f"\nCaller device_secret (keep private): {secrets[CALLER_DEVICE]}")
    if secrets.get(CALLEE_DEVICE):
        print(f"Callee device_secret (keep private): {secrets[CALLEE_DEVICE]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
