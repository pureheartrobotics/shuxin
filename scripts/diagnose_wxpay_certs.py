#!/usr/bin/env python3
"""Diagnose WeChat Pay platform certificate fetch (run inside voice container or with .env)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    from shuxin.voice import wechat_pay

    print("configured:", wechat_pay.wechat_pay_configured())
    print("public_key_mode:", wechat_pay.uses_wechat_pay_public_key())
    print("private_key:", wechat_pay._private_key_path(), "exists=", wechat_pay._private_key_path().is_file())
    print("platform_dir:", wechat_pay._platform_cert_dir())
    print("mchid:", wechat_pay._mch_id()[:4] + "***" if wechat_pay._mch_id() else "(empty)")
    print("serial:", (wechat_pay._cert_serial_no()[:8] + "***") if wechat_pay._cert_serial_no() else "(empty)")

    try:
        detail = wechat_pay.diagnose_platform_certificates()
        print(json.dumps(detail, ensure_ascii=False, indent=2))
        return 0 if detail.get("ok") else 1
    except Exception as exc:
        print("ERROR:", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
