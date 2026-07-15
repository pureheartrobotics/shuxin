#!/usr/bin/env python3
"""Quick feedback loop: vendored SDK size + Node vm export check.

  python3 scripts/check_brtc_web_sdk_load.py
  python3 scripts/check_brtc_web_sdk_load.py --base http://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_PATH = ROOT / "src" / "shuxin" / "voice" / "static" / "js" / "baidu.rtc.sdk.js"
MIN_BYTES = 100_000


def _check_file(path: Path) -> None:
    raw = path.read_bytes()
    print(f"file bytes={len(raw)} path={path}")
    if len(raw) < MIN_BYTES:
        raise SystemExit(f"FAIL: SDK too small ({len(raw)}); placeholder?")
    text = raw.decode("utf-8", errors="replace")
    if "window.BRTC_Start=function" not in text and "window.BRTC_Start = function" not in text:
        raise SystemExit("FAIL: window.BRTC_Start=function not found in bundle")
    print("file: window.BRTC_Start export string OK")


def _check_url(base: str) -> None:
    url = base.rstrip("/") + "/voice-static/js/baidu.rtc.sdk.js"
    with urllib.request.urlopen(url, timeout=15) as resp:
        raw = resp.read()
    print(f"http bytes={len(raw)} url={url}")
    if len(raw) < MIN_BYTES:
        raise SystemExit(f"FAIL: served SDK too small ({len(raw)})")
    text = raw.decode("utf-8", errors="replace")
    if "window.BRTC_Start=function" not in text:
        raise SystemExit("FAIL: served SDK missing window.BRTC_Start=function")
    print("http: OK")


def _check_node_vm() -> None:
    # Reuse pytest node snippet via running the test module's approach inline.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_brtc_web_sdk_bundle.py", "-q"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    print(result.stdout or "")
    if result.returncode != 0:
        print(result.stderr or "", file=sys.stderr)
        raise SystemExit("FAIL: pytest test_brtc_web_sdk_bundle")
    print("node-vm via pytest: OK")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Baidu BRTC Web SDK bundle")
    parser.add_argument("--base", default="", help="Optional voice base URL to curl SDK")
    parser.add_argument("--skip-pytest", action="store_true")
    args = parser.parse_args()
    _check_file(SDK_PATH)
    if args.base:
        _check_url(args.base)
    if not args.skip_pytest:
        _check_node_vm()
    print("ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
