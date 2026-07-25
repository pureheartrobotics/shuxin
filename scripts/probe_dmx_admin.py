#!/usr/bin/env python3
"""Probe DMX admin credentials (no secrets printed).

Usage (Docker)::

    docker exec shuxin-voice-demo-pg python /app/scripts/probe_dmx_admin.py

Exit 0 if GET+POST /api/token/ succeed; non-zero on auth failure.
"""

from __future__ import annotations

import os
import sys

import httpx


def main() -> int:
    base = os.environ.get("DMX_API_BASE_URL", "https://www.dmxapi.cn").rstrip("/")
    tok = (os.environ.get("DMX_SYSTEM_TOKEN") or "").strip()
    uid = (os.environ.get("DMX_API_USER_ID") or "").strip()
    print(f"base={base}")
    print(f"configured={bool(tok and uid)} token_len={len(tok)} user_id_len={len(uid)}")
    if not (tok and uid):
        print("FAIL: DMX_SYSTEM_TOKEN or DMX_API_USER_ID missing")
        return 2
    headers = {
        "Authorization": f"Bearer {tok}",
        "Rix-Api-User": uid,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    with httpx.Client(timeout=20.0) as client:
        get_res = client.get(
            f"{base}/api/token/",
            headers=headers,
            params={"p": 0, "page_size": 1},
        )
        print(f"GET /api/token/ status={get_res.status_code}")
        print(f"GET body_snip={(get_res.text or '')[:180]}")
        if get_res.status_code == 401:
            print(
                "FAIL: AUTH_UNAUTHORIZED — update DMX_SYSTEM_TOKEN / DMX_API_USER_ID "
                "in .env then: bash scripts/redeploy_docker.sh --skip-build"
            )
            return 1
        post_res = client.post(
            f"{base}/api/token/",
            headers=headers,
            json={
                "name": "probe_shuxin_diag_do_not_use",
                "unlimited_quota": True,
                "remain_quota": 0,
                "unlimited_count": True,
                "remain_count": 0,
                "expired_time": -1,
                "group": "default",
                "model_limits_enabled": False,
                "model_limits": "",
                "allow_ips": "",
                "exclude_ips": "",
            },
        )
        print(f"POST /api/token/ status={post_res.status_code}")
        print(f"POST body_snip={(post_res.text or '')[:180]}")
        if post_res.status_code == 401:
            print("FAIL: POST unauthorized (same as production soft-user provision)")
            return 1
        if post_res.status_code >= 400:
            print("FAIL: POST not OK")
            return 1
    print("OK: DMX admin can list/create tokens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
