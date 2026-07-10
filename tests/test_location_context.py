import json
from pathlib import Path

from shuxin.integrations.location.context import (
    format_location_context_block,
    resolve_location_context,
)
from shuxin.integrations.location.provider import LocationContext


def _ip_payload(city: str, adcode: str, district: str = "") -> str:
    return json.dumps(
        {
            "status": 0,
            "content": {
                "address": f"{city}",
                "address_detail": {
                    "province": city.replace("市", "省") if "市" in city else city,
                    "city": city,
                    "district": district,
                    "adcode": adcode,
                },
                "point": {"x": "12950000", "y": "4800000"},
            },
        },
        ensure_ascii=False,
    )


class _StubProvider:
    def __init__(self, *, city: str = "上海市", adcode: str = "310100") -> None:
        self.city = city
        self.adcode = adcode
        self.ip_calls = 0

    def is_available(self) -> bool:
        return True

    def call_tool(self, name: str, arguments: dict) -> str:
        self.ip_calls += 1
        assert name == "map_ip_location"
        return _ip_payload(self.city, self.adcode)


def test_foreign_ip_label_falls_back_to_profile(tmp_path: Path):
    user_home = tmp_path / "user1"
    user_home.mkdir(parents=True)
    (user_home / "user_profile.json").write_text(
        json.dumps({"location": "杭州市"}, ensure_ascii=False),
        encoding="utf-8",
    )

    class _ForeignProvider(_StubProvider):
        def call_tool(self, name: str, arguments: dict) -> str:
            return json.dumps(
                {
                    "status": 0,
                    "content": {
                        "address": "TokyoKoto",
                        "address_detail": {"city": "Koto", "adcode": "0"},
                    },
                }
            )

    ctx = resolve_location_context(_ForeignProvider(), ip="8.8.8.8", user_home=user_home)

    assert ctx.label == "杭州市"
    assert ctx.source == "profile"
    assert ctx.confidence == "low"


def test_ip_location_takes_priority_over_profile(tmp_path: Path):
    user_home = tmp_path / "user1"
    user_home.mkdir(parents=True)
    (user_home / "user_profile.json").write_text(
        json.dumps({"location": "杭州市"}, ensure_ascii=False),
        encoding="utf-8",
    )

    provider = _StubProvider(city="北京市", adcode="110100")
    ctx = resolve_location_context(provider, ip="8.8.8.8", user_home=user_home)

    assert ctx.label == "北京市"
    assert ctx.city == "北京市"
    assert ctx.city_adcode == "110100"
    assert ctx.source == "ip"
    assert ctx.confidence == "medium"
    assert provider.ip_calls == 1


def test_ip_slot4_uses_city_not_district():
    ctx = LocationContext(label="深圳市", city="深圳市", source="ip", confidence="medium")
    block = format_location_context_block(ctx)
    assert "深圳市" in block
    assert "区级可能有偏差" in block


def test_profile_used_when_ip_fails(tmp_path: Path):
    user_home = tmp_path / "user1"
    user_home.mkdir(parents=True)
    (user_home / "user_profile.json").write_text(
        json.dumps({"location": "杭州市"}, ensure_ascii=False),
        encoding="utf-8",
    )

    class _FailProvider(_StubProvider):
        def call_tool(self, name: str, arguments: dict) -> str:
            return json.dumps({"error": "fail"})

    ctx = resolve_location_context(_FailProvider(), ip="8.8.8.8", user_home=user_home)

    assert ctx.label == "杭州市"
    assert ctx.source == "profile"
    assert ctx.confidence == "low"


def test_default_region_when_ip_and_profile_missing(monkeypatch):
    monkeypatch.setenv("SHUXIN_MAP_DEFAULT_REGION", "深圳市")

    class _FailProvider(_StubProvider):
        def call_tool(self, name: str, arguments: dict) -> str:
            return ""

    ctx = resolve_location_context(_FailProvider(), ip="8.8.8.8", user_home=None)

    assert ctx.label == "深圳市"
    assert ctx.source == "default"
    assert ctx.confidence == "low"


def test_format_low_confidence_block():
    block = format_location_context_block(
        LocationContext(label="杭州市", source="profile", confidence="low")
    )
    assert "推测可能" in block
    assert "勿当作用户已确认地址" in block


def test_foreign_ip_explicit_mcp_message():
    class _USProvider(_StubProvider):
        def call_tool(self, name: str, arguments: dict) -> str:
            return json.dumps(
                {
                    "status": 0,
                    "content": {
                        "address": "CaliforniaLos Angeles",
                        "address_detail": {
                            "province": "California",
                            "city": "Los Angeles",
                            "nation": "United States",
                            "nation_code": "USA",
                            "adcode": "0",
                        },
                    },
                }
            )

    ctx = resolve_location_context(_USProvider(), ip="8.8.8.8", user_home=None)
    assert "Los Angeles" in ctx.label
    assert ctx.source == "foreign"
    assert ctx.confidence == "low"

    block = format_location_context_block(ctx)
    assert "国外地区" in block
    assert "没有接入国外" in block
