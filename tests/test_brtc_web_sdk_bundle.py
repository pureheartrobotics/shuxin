"""Guard: vendored Baidu Web RTC SDK must export window.BRTC_Start (not a placeholder)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SDK_PATH = ROOT / "src" / "shuxin" / "voice" / "static" / "js" / "baidu.rtc.sdk.js"
MIN_BYTES = 100_000


def test_brtc_sdk_file_is_real_bundle() -> None:
    assert SDK_PATH.is_file(), f"missing {SDK_PATH}"
    raw = SDK_PATH.read_bytes()
    assert len(raw) >= MIN_BYTES, f"SDK too small ({len(raw)} bytes); placeholder?"
    text = raw.decode("utf-8", errors="replace")
    assert "window.BRTC_Start=function" in text or "window.BRTC_Start = function" in text


def test_brtc_sdk_loads_in_node_vm() -> None:
    """Eval the bundle under a minimal DOM; BRTC_Start must become a function."""
    node = subprocess.run(
        ["node", "-e", _NODE_CHECK],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if node.returncode == 127 or "not found" in (node.stderr or "").lower():
        pytest.skip("node not available")
    assert node.returncode == 0, node.stderr or node.stdout
    assert "OK" in (node.stdout or "")


_NODE_CHECK = r"""
const fs = require("fs");
const vm = require("vm");
const path = require("path");
const sdk = path.join("src", "shuxin", "voice", "static", "js", "baidu.rtc.sdk.js");
const code = fs.readFileSync(sdk, "utf8");
function el() {
  return { style: {}, appendChild() {}, setAttribute() {}, getElementsByTagName: () => [], children: [] };
}
const document = {
  createElement: () => el(),
  getElementsByTagName: (t) => (t === "head" ? [el()] : []),
  getElementById: () => null,
  querySelector: () => null,
  head: el(),
  body: el(),
  documentElement: el(),
  readyState: "complete",
  addEventListener() {},
  createTextNode: () => ({}),
};
const window = {
  document,
  navigator: { userAgent: "Mozilla/5.0 Chrome/120", mediaDevices: {} },
  location: {
    href: "http://127.0.0.1:8765/",
    protocol: "http:",
    hostname: "127.0.0.1",
    host: "127.0.0.1:8765",
  },
  console,
  setTimeout,
  clearTimeout,
  setInterval,
  clearInterval,
  RTCPeerConnection: function () {},
  WebSocket: function () {},
  MutationObserver: function () {
    this.observe = () => {};
  },
};
window.window = window;
window.self = window;
window.top = window;
window.parent = window;
document.defaultView = window;
vm.runInNewContext(code, window, { timeout: 5000 });
if (typeof window.BRTC_Start !== "function") {
  console.error("BRTC_Start missing after eval");
  process.exit(1);
}
console.log("OK", typeof window.BRTC_Version === "function" ? window.BRTC_Version() : "");
"""
