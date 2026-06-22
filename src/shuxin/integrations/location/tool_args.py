"""百度 MCP 工具参数归一化 — 对齐真实 schema。"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from shuxin.integrations.location.provider import LocationContext

_COORD_PAIR = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
_POI_DEFAULT_RADIUS = 3000


def city_adcode_from_district(adcode: str) -> str:
    """区级 adcode → 市级 adcode（440305 → 440300）。"""
    code = (adcode or "").strip()
    if len(code) >= 6 and code.isdigit():
        return code[:4] + "00"
    return ""


def _is_china_flag(raw: dict, ctx: Optional[LocationContext]) -> str:
    for key in ("is_china", "is_chinese_mainland"):
        val = raw.get(key)
        if val is not None:
            if isinstance(val, bool):
                return "true" if val else "false"
            text = str(val).strip().lower()
            if text in ("true", "1", "yes", "false", "0", "no"):
                return "true" if text in ("true", "1", "yes") else "false"
    if ctx and ctx.source == "ip":
        return "true"
    return "true"


def _parse_coord_string(value: str) -> Optional[tuple[float, float]]:
    match = _COORD_PAIR.match(value or "")
    if not match:
        return None
    lat = float(match.group(1))
    lng = float(match.group(2))
    # MCP weather: 经度在前；POI: lat,lng — 按数值范围猜测
    if abs(lat) > 90 and abs(lng) <= 90:
        lat, lng = lng, lat
    if abs(lat) <= 90 and abs(lng) <= 180:
        return lat, lng
    return None


def normalize_map_weather_args(
    raw: Dict[str, Any],
    ctx: Optional[LocationContext] = None,
) -> Optional[Dict[str, str]]:
    """将各类 map_weather 入参转为 MCP 可接受的 district_id 或 location(经纬度)。"""
    if not isinstance(raw, dict):
        raw = {}

    is_china = _is_china_flag(raw, ctx)

    district_id = str(raw.get("district_id") or "").strip()
    if district_id.isdigit() and len(district_id) == 6:
        # 天气用市级 adcode，避免误报区级
        city_code = city_adcode_from_district(district_id)
        return {"district_id": city_code or district_id, "is_china": is_china}

    if ctx and ctx.city_adcode:
        return {"district_id": ctx.city_adcode, "is_china": is_china}

    location_raw = str(raw.get("location") or "").strip()
    coords = _parse_coord_string(location_raw)
    if coords:
        lat, lng = coords
        return {"location": f"{lng},{lat}", "is_china": is_china}

    if ctx and ctx.lat and ctx.lng:
        return {"location": f"{ctx.lng},{ctx.lat}", "is_china": is_china}

    # region/location 为城市名时无法直接查天气，依赖 ctx.city_adcode
    if ctx and ctx.city_adcode:
        return {"district_id": ctx.city_adcode, "is_china": is_china}

    region_name = str(raw.get("region") or raw.get("location") or "").strip()
    if region_name and ctx and ctx.city:
        city_key = ctx.city.replace("市", "")
        if city_key and city_key in region_name.replace("市", ""):
            if ctx.city_adcode:
                return {"district_id": ctx.city_adcode, "is_china": is_china}

    return None


def normalize_map_search_places_args(
    raw: Dict[str, Any],
    ctx: Optional[LocationContext] = None,
    *,
    default_query: str = "美食",
) -> Optional[Dict[str, Any]]:
    """POI 检索：优先坐标半径，其次城市级 region。"""
    if not isinstance(raw, dict):
        raw = {}

    query = str(raw.get("query") or default_query).strip() or default_query
    tag = str(raw.get("tag") or query).strip() or query
    args: Dict[str, Any] = {"query": query, "tag": tag}

    location_raw = str(raw.get("location") or "").strip()
    coords = _parse_coord_string(location_raw)
    if coords:
        lat, lng = coords
        args["location"] = f"{lat},{lng}"
        args["radius"] = int(raw.get("radius") or _POI_DEFAULT_RADIUS)
        return args

    if ctx and ctx.lat and ctx.lng and ctx.source != "ip":
        args["location"] = f"{ctx.lat},{ctx.lng}"
        args["radius"] = int(raw.get("radius") or _POI_DEFAULT_RADIUS)
        return args

    region = str(raw.get("region") or "").strip()
    if not region and ctx:
        region = ctx.city or ctx.label
    if region:
        args["region"] = region
        args["is_chinese_mainland"] = _is_china_flag(raw, ctx)
        return args

    return None
