"""地图能力提供者抽象接口。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


VOICE_TOOL_WHITELIST: frozenset[str] = frozenset(
    {
        "map_weather",
        "map_search_places",
        "map_directions",
        "map_geocode",
        "map_reverse_geocode",
    }
)

CLI_TOOL_WHITELIST: frozenset[str] = VOICE_TOOL_WHITELIST | frozenset(
    {
        "map_place_details",
        "map_directions_matrix",
        "map_road_traffic",
    }
)

INTERNAL_TOOLS: frozenset[str] = frozenset({"map_ip_location"})


@dataclass
class LocationContext:
    """服务端解析的用户大致位置。"""

    label: str = ""
    city: str = ""
    district: str = ""
    district_id: str = ""
    city_adcode: str = ""
    lat: float = 0.0
    lng: float = 0.0
    source: str = ""  # ip | profile | default | none
    confidence: str = ""  # high | medium | low

    def to_metadata_dict(self) -> dict:
        return {
            "label": self.label,
            "city": self.city,
            "district": self.district,
            "district_id": self.district_id,
            "city_adcode": self.city_adcode,
            "lat": self.lat,
            "lng": self.lng,
            "source": self.source,
            "confidence": self.confidence,
        }

    @classmethod
    def from_metadata_dict(cls, raw: dict) -> "LocationContext":
        return cls(
            label=str(raw.get("label") or ""),
            city=str(raw.get("city") or ""),
            district=str(raw.get("district") or ""),
            district_id=str(raw.get("district_id") or ""),
            city_adcode=str(raw.get("city_adcode") or ""),
            lat=float(raw.get("lat") or 0),
            lng=float(raw.get("lng") or 0),
            source=str(raw.get("source") or ""),
            confidence=str(raw.get("confidence") or ""),
        )


@runtime_checkable
class LocationToolProvider(Protocol):
    """地图工具提供者 — MCP 或 REST 实现可互换。"""

    def is_available(self) -> bool:
        """是否已配置且可用。"""
        ...

    def list_openai_tools(self, *, channel: str = "voice") -> List[Dict[str, Any]]:
        """返回 OpenAI function calling 格式的 tools 列表。"""
        ...

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        """同步调用工具，返回 JSON 字符串。"""
        ...

    def resolve_location_context(
        self,
        *,
        ip: Optional[str] = None,
        user_home: Optional[Path] = None,
    ) -> LocationContext:
        """静默解析用户大致位置（不经过 LLM tool round）。"""
        ...
