"""Qiniu Kodo + CDN public URL helpers.

Scheme A: objects live in Kodo; clients read via the bound Fusion CDN domain.
Upload/management APIs are out of scope here — only outbound URL assembly.
"""

from __future__ import annotations

import os
from typing import Any, Dict


def qiniu_config() -> Dict[str, Any]:
    """Read Qiniu settings from environment (empty strings when unset)."""
    domain = str(os.environ.get("SHUXIN_QINIU_CDN_DOMAIN") or "").strip()
    for prefix in ("https://", "http://"):
        if domain.lower().startswith(prefix):
            domain = domain[len(prefix) :]
            break
    domain = domain.rstrip("/")
    use_https = str(os.environ.get("SHUXIN_QINIU_USE_HTTPS") or "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    return {
        "access_key": str(os.environ.get("SHUXIN_QINIU_ACCESS_KEY") or "").strip(),
        "secret_key": str(os.environ.get("SHUXIN_QINIU_SECRET_KEY") or "").strip(),
        "bucket": str(os.environ.get("SHUXIN_QINIU_BUCKET") or "").strip(),
        "cdn_domain": domain,
        "use_https": use_https,
    }


def public_url(key_or_url: str) -> str:
    """Return a browser-ready URL for a Kodo key or pass through absolute URLs.

    - Absolute ``http(s)://`` / ``//`` values are returned unchanged (trimmed).
    - Relative object keys are joined with ``SHUXIN_QINIU_CDN_DOMAIN`` when set.
    - If CDN domain is unset, relative keys are returned as-is (no crash).
    """
    raw = str(key_or_url or "").strip()
    if not raw:
        return ""
    lower = raw.lower()
    if lower.startswith("http://") or lower.startswith("https://") or raw.startswith("//"):
        return raw

    cfg = qiniu_config()
    domain = cfg["cdn_domain"]
    if not domain:
        return raw.lstrip("/")

    key = raw.lstrip("/")
    scheme = "https" if cfg["use_https"] else "http"
    return f"{scheme}://{domain}/{key}"


def public_url_with_version(key_or_url: str, version: str = "") -> str:
    """``public_url`` plus optional ``?v=`` / ``&v=`` cache-buster."""
    base = public_url(key_or_url)
    ver = str(version or "").strip()
    if not base or not ver:
        return base
    from urllib.parse import quote

    sep = "&" if "?" in base else "?"
    return "%s%sv=%s" % (base, sep, quote(ver, safe=""))
