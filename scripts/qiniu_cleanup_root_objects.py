#!/usr/bin/env python3
"""One-shot cleanup: delete Qiniu Kodo objects whose keys have no '/' (bucket root).

Keeps prefixed paths such as test/...  Does not print AccessKey/SecretKey.

Usage (repo root):
  python3 scripts/qiniu_cleanup_root_objects.py --dry-run
  python3 scripts/qiniu_cleanup_root_objects.py --execute
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

LIST_HOSTS = (
    "rsf-z2.qiniuapi.com",  # South China (matches up-z2 upload region)
    "rsf.qiniuapi.com",
)
RS_HOSTS = (
    "rs-z2.qiniuapi.com",
    "rs.qiniuapi.com",
)
BATCH_SIZE = 1000
SAMPLE_LIMIT = 20


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.split("#", 1)[0].strip().strip('"').strip("'")
        if key.startswith("SHUXIN_QINIU_") and key not in os.environ:
            os.environ[key] = value


def _require_creds() -> Tuple[str, str, str, str]:
    ak = (os.environ.get("SHUXIN_QINIU_ACCESS_KEY") or "").strip()
    sk = (os.environ.get("SHUXIN_QINIU_SECRET_KEY") or "").strip()
    bucket = (os.environ.get("SHUXIN_QINIU_BUCKET") or "").strip()
    domain = (os.environ.get("SHUXIN_QINIU_CDN_DOMAIN") or "").strip()
    for prefix in ("https://", "http://"):
        if domain.lower().startswith(prefix):
            domain = domain[len(prefix) :]
            break
    domain = domain.rstrip("/")
    if not ak or not sk or not bucket:
        print("error: missing SHUXIN_QINIU_ACCESS_KEY / SECRET_KEY / BUCKET", file=sys.stderr)
        sys.exit(2)
    return ak, sk, bucket, domain


def _urlsafe_b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _qbox_authorization(ak: str, sk: str, path_with_query: str, body: bytes = b"") -> str:
    """QBox token for management APIs (path + optional form body)."""
    signing = path_with_query + "\n"
    if body:
        signing += body.decode("utf-8") if isinstance(body, bytes) else str(body)
    digest = hmac.new(sk.encode("utf-8"), signing.encode("utf-8"), hashlib.sha1).digest()
    return "QBox %s:%s" % (ak, _urlsafe_b64(digest))


def _encoded_entry(bucket: str, key: str) -> str:
    return _urlsafe_b64(("%s:%s" % (bucket, key)).encode("utf-8"))


def _http(
    method: str,
    host: str,
    path_with_query: str,
    ak: str,
    sk: str,
    body: Optional[bytes] = None,
    content_type: str = "application/x-www-form-urlencoded",
) -> Tuple[int, bytes]:
    data = body if body is not None else None
    auth_body = data if (data and content_type == "application/x-www-form-urlencoded") else b""
    headers = {
        "Host": host,
        "Authorization": _qbox_authorization(ak, sk, path_with_query, auth_body),
        "Content-Type": content_type,
        "User-Agent": "shuxin-qiniu-cleanup/1.0",
    }
    url = "https://%s%s" % (host, path_with_query)
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.getcode(), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read() if exc.fp else b""


def list_root_keys(ak: str, sk: str, bucket: str) -> Tuple[str, List[str], int]:
    """List keys with no '/' using delimiter=/ (root files only).

    Returns (list_host_used, root_keys, prefixed_hint_count).
    prefixed_hint_count is number of commonPrefixes seen (directories), not file count.
    """
    last_error = ""
    for host in LIST_HOSTS:
        root_keys: List[str] = []
        marker = ""
        common_prefix_count = 0
        ok = True
        while True:
            query = {
                "bucket": bucket,
                "limit": "1000",
                "delimiter": "/",
            }
            if marker:
                query["marker"] = marker
            path = "/list?" + urllib.parse.urlencode(query)
            code, raw = _http("GET", host, path, ak, sk)
            if code != 200:
                last_error = "host=%s status=%s body=%s" % (
                    host,
                    code,
                    raw.decode("utf-8", errors="replace")[:300],
                )
                ok = False
                break
            payload: Dict[str, Any] = json.loads(raw.decode("utf-8"))
            for item in payload.get("items") or []:
                key = str(item.get("key") or "")
                if key and "/" not in key:
                    root_keys.append(key)
            for prefix in payload.get("commonPrefixes") or []:
                if prefix:
                    common_prefix_count += 1
            marker = str(payload.get("marker") or "")
            if not marker:
                break
        if ok:
            return host, root_keys, common_prefix_count
    print("error: list failed: %s" % last_error, file=sys.stderr)
    sys.exit(3)


def count_prefixed_objects(ak: str, sk: str, bucket: str, list_host: str) -> int:
    """Count objects whose keys contain '/' (non-root)."""
    total = 0
    marker = ""
    while True:
        query = {"bucket": bucket, "limit": "1000"}
        if marker:
            query["marker"] = marker
        path = "/list?" + urllib.parse.urlencode(query)
        code, raw = _http("GET", list_host, path, ak, sk)
        if code != 200:
            print(
                "warn: full list failed status=%s" % code,
                file=sys.stderr,
            )
            return -1
        payload = json.loads(raw.decode("utf-8"))
        for item in payload.get("items") or []:
            key = str(item.get("key") or "")
            if "/" in key:
                total += 1
        marker = str(payload.get("marker") or "")
        if not marker:
            break
    return total


def batch_delete(ak: str, sk: str, bucket: str, keys: List[str]) -> None:
    if not keys:
        print("nothing to delete")
        return
    last_error = ""
    for host in RS_HOSTS:
        failed = False
        for i in range(0, len(keys), BATCH_SIZE):
            chunk = keys[i : i + BATCH_SIZE]
            ops = ["op=/delete/%s" % _encoded_entry(bucket, key) for key in chunk]
            body = "&".join(ops).encode("utf-8")
            code, raw = _http("POST", host, "/batch", ak, sk, body=body)
            if code not in (200,):
                # 298 = partial success in some qiniu docs; treat non-2xx carefully
                last_error = "host=%s status=%s body=%s" % (
                    host,
                    code,
                    raw.decode("utf-8", errors="replace")[:400],
                )
                failed = True
                break
            try:
                results = json.loads(raw.decode("utf-8"))
            except Exception:
                results = []
            bad = [
                (idx, item)
                for idx, item in enumerate(results)
                if isinstance(item, dict) and int(item.get("code") or 0) not in (200, 612)
            ]
            # 612 = no such file (already gone) — ok
            if bad:
                sample = bad[:3]
                print(
                    "warn: batch partial failures count=%s sample=%s"
                    % (len(bad), sample),
                    file=sys.stderr,
                )
            print(
                "deleted_batch host=%s offset=%s size=%s http=%s"
                % (host, i, len(chunk), code)
            )
        if not failed:
            return
    print("error: batch delete failed: %s" % last_error, file=sys.stderr)
    sys.exit(4)


def check_cdn(domain: str, key: str = "test/image.png") -> int:
    if not domain:
        print("cdn_check=skipped (no SHUXIN_QINIU_CDN_DOMAIN)")
        return 0
    url = "https://%s/%s" % (domain, key)
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            code = resp.getcode()
            raw = resp.read()
            print("cdn_check url=%s http=%s bytes=%s" % (url, code, len(raw)))
            return int(code)
    except urllib.error.HTTPError as exc:
        print("cdn_check url=%s http=%s" % (url, exc.code))
        return int(exc.code)
    except Exception as exc:
        print("cdn_check error=%s" % type(exc).__name__)
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete Qiniu bucket root objects (no '/' in key).")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="List only; do not delete")
    mode.add_argument("--execute", action="store_true", help="Delete root objects")
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to env file (default: .env in cwd)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    env_path = Path(args.env_file)
    if not env_path.is_file():
        env_path = repo_root / args.env_file
    _load_dotenv(env_path)

    ak, sk, bucket, domain = _require_creds()
    list_host, root_keys, dir_hint = list_root_keys(ak, sk, bucket)
    prefixed_before = count_prefixed_objects(ak, sk, bucket, list_host)

    print("bucket=%s list_host=%s" % (bucket, list_host))
    print("root_key_count=%s" % len(root_keys))
    print("common_prefix_dirs=%s" % dir_hint)
    print("prefixed_object_count=%s" % prefixed_before)
    samples = root_keys[:SAMPLE_LIMIT]
    print("root_key_samples=%s" % json.dumps(samples, ensure_ascii=False))
    if len(root_keys) > SAMPLE_LIMIT:
        print("root_key_samples_truncated=%s" % (len(root_keys) - SAMPLE_LIMIT))

    if args.dry_run:
        print("mode=dry-run (no delete)")
        check_cdn(domain)
        return

    print("mode=execute")
    batch_delete(ak, sk, bucket, root_keys)

    list_host2, root_after, _ = list_root_keys(ak, sk, bucket)
    prefixed_after = count_prefixed_objects(ak, sk, bucket, list_host2)
    print("root_key_count_after=%s" % len(root_after))
    print("prefixed_object_count_after=%s" % prefixed_after)
    cdn_code = check_cdn(domain)

    if root_after:
        print("error: root keys remain: %s" % root_after[:SAMPLE_LIMIT], file=sys.stderr)
        sys.exit(5)
    if prefixed_before >= 0 and prefixed_after >= 0 and prefixed_after != prefixed_before:
        print(
            "error: prefixed count changed %s -> %s"
            % (prefixed_before, prefixed_after),
            file=sys.stderr,
        )
        sys.exit(6)
    if domain and cdn_code != 200:
        print("error: CDN smoke failed for test/image.png", file=sys.stderr)
        sys.exit(7)
    print("cleanup_ok=true")


if __name__ == "__main__":
    main()
