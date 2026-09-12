"""客户端 IP 解析 — localhost/私网时改用服务器出口公网 IP。"""

from __future__ import annotations

import ipaddress
import logging
import re
from typing import Optional

import httpx

logger = logging.getLogger("shuxin.integrations.location.ip_resolve")

_EGRESS_IP_URLS = (
    "https://api.ipify.org",
    "http://ifconfig.me/ip",
    "https://ifconfig.me/ip",
)
_EGRESS_TIMEOUT_SECONDS = 3.0
_cached_egress_ip: Optional[str] = None
_cached_egress_time: float = 0.0
_EGRESS_CACHE_TTL = 30.0
_IP_PATTERN = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def is_private_or_loopback(ip: str) -> bool:
    text = (ip or "").strip()
    if not text:
        return True
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return True
    return bool(addr.is_private or addr.is_loopback or addr.is_link_local)


def _parse_ip_text(body: str) -> Optional[str]:
    ip = (body or "").strip().splitlines()[0].strip()
    if _IP_PATTERN.match(ip) and not is_private_or_loopback(ip):
        return ip
    return None


def fetch_egress_public_ip() -> Optional[str]:
    """获取当前环境出口公网 IP（带进程内缓存，30秒 TTL）。"""
    global _cached_egress_ip, _cached_egress_time
    import time

    now = time.time()
    if _cached_egress_ip and (now - _cached_egress_time) < _EGRESS_CACHE_TTL:
        return _cached_egress_ip

    for url in _EGRESS_IP_URLS:
        try:
            response = httpx.get(url, timeout=_EGRESS_TIMEOUT_SECONDS)
            response.raise_for_status()
            ip = _parse_ip_text(response.text)
            if ip:
                _cached_egress_ip = ip
                _cached_egress_time = now
                logger.info("出口公网 IP (%s): %s", url, ip)
                return ip
        except Exception as exc:
            logger.warning("获取出口公网 IP 失败 [%s]: %s", url, exc)
    return None


def resolve_effective_ip(client_ip: Optional[str]) -> Optional[str]:
    raw = (client_ip or "").strip()
    if raw and not is_private_or_loopback(raw):
        return raw
    if raw:
        logger.debug("client_ip=%s 为私网/回环，尝试出口公网 IP", raw)
    return fetch_egress_public_ip()


def clear_egress_ip_cache() -> None:
    global _cached_egress_ip, _cached_egress_time
    _cached_egress_ip = None
    _cached_egress_time = 0.0
