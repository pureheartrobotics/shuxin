"""位置上下文解析 — IP 优先，画像/默认城市为低置信 fallback。"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from shuxin.integrations.location.bd09mc import bd09mc_to_bd09ll, is_plausible_latlng
from shuxin.integrations.location.provider import LocationContext
from shuxin.integrations.location.tool_args import city_adcode_from_district

if TYPE_CHECKING:
    from shuxin.integrations.location.provider import LocationToolProvider

logger = logging.getLogger("shuxin.integrations.location.context")

_DEFAULT_REGION_ENV = "SHUXIN_MAP_DEFAULT_REGION"

_FOREIGN_LOCATION_MARKERS: tuple[str, ...] = (
    "东京",
    "日本",
    "大阪",
    "京都",
    "横滨",
    "奈良",
    "韩国",
    "首尔",
    "Tokyo",
    "Osaka",
    "Japan",
    "Korea",
    "Seoul",
)


def _is_plausible_china_location(label: str) -> bool:
    text = (label or "").strip()
    if not text:
        return False
    if any(marker in text for marker in _FOREIGN_LOCATION_MARKERS):
        return False
    if any("A" <= c <= "Z" or "a" <= c <= "z" for c in text):
        return False
    chinese = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return chinese >= 2


def _profile_location(user_home: Optional[Path]) -> str:
    if user_home is None:
        return ""
    profile_file = user_home / "user_profile.json"
    if not profile_file.exists():
        return ""
    try:
        data = json.loads(profile_file.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return str(data.get("location") or "").strip()
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("读取用户画像 location 失败: %s", exc)
    return ""


def _default_region() -> str:
    return os.environ.get(_DEFAULT_REGION_ENV, "").strip()


def _extract_city_name(city: str, province: str = "") -> str:
    text = (city or "").strip()
    if text:
        return text if text.endswith("市") else f"{text}市" if len(text) <= 8 else text
    return ""


def _parse_ip_location_structured(raw: str) -> Optional[LocationContext]:
    if not raw or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        text = raw.strip()
        if "Authentication failed" in text or "IP校验失败" in text:
            return None
        if _is_plausible_china_location(text):
            return LocationContext(label=text, source="ip", confidence="medium")
        return None

    if not isinstance(data, dict) or data.get("error"):
        return None

    content = data.get("content") or data
    if isinstance(content, list) and content:
        content = content[0]
    if not isinstance(content, dict):
        return None

    detail = content.get("address_detail") or {}
    province = str(detail.get("province") or "").strip()
    city = _extract_city_name(str(detail.get("city") or "").strip(), province)
    district = str(detail.get("district") or "").strip()
    adcode = str(detail.get("adcode") or "").strip()
    city_adcode = city_adcode_from_district(adcode) if adcode and adcode != "0" else ""

    # Slot4 展示市级，不断言不可靠的区级
    label = city or str(content.get("address") or "").strip()
    if province and city and province not in label:
        label = f"{province}{city}".replace("省", "省")

    if not label or not _is_plausible_china_location(label):
        return None

    lat = 0.0
    lng = 0.0
    point = content.get("point") or {}
    try:
        px = float(point.get("x") or 0)
        py = float(point.get("y") or 0)
        if px and py:
            lat, lng = bd09mc_to_bd09ll(px, py)
            if not is_plausible_latlng(lat, lng):
                lat, lng = 0.0, 0.0
    except (TypeError, ValueError):
        pass

    return LocationContext(
        label=city or label,
        city=city,
        district=district,
        district_id=adcode if adcode != "0" else "",
        city_adcode=city_adcode,
        lat=lat,
        lng=lng,
        source="ip",
        confidence="medium",
    )


def _resolve_from_ip(provider: "LocationToolProvider", ip: Optional[str]) -> LocationContext:
    if not provider.is_available() or not ip:
        return LocationContext()
    try:
        raw = provider.call_tool("map_ip_location", {"ip": ip})
        ctx = _parse_ip_location_structured(raw)
        if ctx and ctx.label:
            return ctx
        # 海外等不可信结果
        try:
            data = json.loads(raw)
            addr = (
                (data.get("content") or {}).get("address")
                if isinstance(data, dict)
                else None
            )
            if addr:
                logger.info("IP 定位结果非中国大陆，丢弃: %s", addr)
        except json.JSONDecodeError:
            pass
    except Exception as exc:
        logger.warning("IP 位置解析失败: %s", exc)
    return LocationContext()


def resolve_location_context(
    provider: "LocationToolProvider",
    *,
    ip: Optional[str] = None,
    user_home: Optional[Path] = None,
    default_region: Optional[str] = None,
) -> LocationContext:
    ip_ctx = _resolve_from_ip(provider, ip)
    if ip_ctx.label:
        return ip_ctx

    profile_city = _profile_location(user_home)
    if profile_city:
        city = profile_city if profile_city.endswith("市") else profile_city
        return LocationContext(
            label=city,
            city=city,
            source="profile",
            confidence="low",
        )

    default_city = (default_region or "").strip() or _default_region()
    if default_city:
        city = default_city if default_city.endswith("市") else default_city
        return LocationContext(
            label=city,
            city=city,
            source="default",
            confidence="low",
        )

    return LocationContext()


def format_location_context_block(ctx: LocationContext) -> str:
    if not ctx.label:
        return ""
    if ctx.confidence == "low":
        source_hint = {
            "profile": "用户画像推测",
            "default": "开发默认城市",
        }.get(ctx.source, "低置信推测")
        return (
            f"【位置上下文】推测可能在：{ctx.label}（来源：{source_hint}，未经验证，"
            f"勿当作用户已确认地址；表述时用「可能/大概」而非断言）"
        )
    if ctx.source == "ip":
        return (
            f"【位置上下文】用户大致在：{ctx.label}附近（来源：IP 定位，"
            f"区级可能有偏差，勿断言具体行政区；天气按市级查询）"
        )
    return (
        f"【位置上下文】用户大致在：{ctx.label}（来源：{ctx.source}，仅供参考，可追问确认）"
    )
