#!/usr/bin/env python3
"""Seed in-memory RTC call handles via admin API (lab helper).

Example (voice container / host with admin token):

  export SHUXIN_ADMIN_TOKEN=dev-admin-token
  python scripts/seed_rtc_call_demo.py \\
    --base http://127.0.0.1:8765 \\
    --caller-user-id <主叫user_id> --caller-handle alice \\
    --callee-user-id <被叫user_id> --callee-handle bob \\
    --contact-owner <主叫user_id> --contact-name 小明 --contact-handle bob
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed RTC call lab handles")
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    parser.add_argument("--token", default=os.environ.get("SHUXIN_ADMIN_TOKEN", ""))
    parser.add_argument("--caller-user-id", required=True)
    parser.add_argument("--caller-handle", required=True)
    parser.add_argument("--callee-user-id", required=True)
    parser.add_argument("--callee-handle", required=True)
    parser.add_argument("--contact-owner", default="")
    parser.add_argument("--contact-name", default="")
    parser.add_argument("--contact-handle", default="")
    args = parser.parse_args()
    if not args.token:
        print("SHUXIN_ADMIN_TOKEN / --token required", file=sys.stderr)
        return 2

    handles = [
        {"user_id": args.caller_user_id, "handle": args.caller_handle},
        {"user_id": args.callee_user_id, "handle": args.callee_handle},
    ]
    contacts = []
    owner = args.contact_owner or args.caller_user_id
    name = args.contact_name
    th = args.contact_handle or args.callee_handle
    if name:
        contacts.append(
            {
                "owner_user_id": owner,
                "nickname": name,
                "target_handle": th,
            }
        )

    body = json.dumps({"handles": handles, "contacts": contacts}).encode("utf-8")
    req = urllib.request.Request(
        args.base.rstrip("/") + "/admin/api/call-test/seed",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Admin-Token": args.token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8"), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
