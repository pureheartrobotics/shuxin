"""轻量意图门控 — 决定是否为本轮附加地图 tools。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shuxin.core.config import MapConfig

_LOCATION_KEYWORDS: tuple[str, ...] = (
    "天气",
    "气温",
    "下雨",
    "下雪",
    "路线",
    "导航",
    "怎么去",
    "怎么走",
    "多远",
    "多久到",
    "堵车",
    "交通",
    "附近",
    "周边",
    "在哪",
    "在哪里",
    "地址",
    "坐标",
    "经纬度",
    "地图",
    "定位",
    "餐厅",
    "酒店",
    "景点",
    "在什么",
    "哪里",
    "哪儿",
    "什么地方",
    "地名",
    "位置",
    "这个地方",
    "这边",
    "这里",
    "当地",
    "好吃",
    "好吃的",
    "吃什么",
    "美食",
    "weather",
    "route",
    "directions",
    "navigate",
    "nearby",
    "geocode",
    "location",
)

_LOCATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"到.+怎么走"),
    re.compile(r"去.+怎么"),
    re.compile(r".+的天气"),
    re.compile(r"离.+多远"),
    re.compile(r".*在什么.*"),
    re.compile(r"天气怎么样"),
    re.compile(r"现在.*天气"),
)


def may_need_location(message: str) -> bool:
    """判断用户输入是否可能涉及地理/地图能力。"""
    text = (message or "").strip().lower()
    if not text:
        return False
    for keyword in _LOCATION_KEYWORDS:
        if keyword in text:
            return True
    for pattern in _LOCATION_PATTERNS:
        if pattern.search(text):
            return True
    return False


def should_attach_location_tools(message: str, map_config: MapConfig) -> bool:
    """结合配置决定是否附加地图 tools。"""
    if not map_config.gate_enabled:
        return True
    return may_need_location(message)
