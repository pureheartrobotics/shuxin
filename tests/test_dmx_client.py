from __future__ import annotations

import asyncio
import json

import httpx

from shuxin.voice.integrations import dmx_client


def test_create_user_token_returns_sk_key_with_nested_items(monkeypatch) -> None:
    monkeypatch.setenv("DMX_SYSTEM_TOKEN", "admin-token")
    monkeypatch.setenv("DMX_API_USER_ID", "42")
    monkeypatch.setenv("DMX_API_BASE_URL", "https://dmx.example")
    posted: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/token/":
            posted.append(json.loads(request.content.decode("utf-8")))
            return httpx.Response(200, json={"success": True})
        if request.method == "GET" and request.url.path == "/api/token/":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "items": [
                            {"id": 1, "name": "wx_user_1", "key": "old-masked", "created_time": 1},
                            {"id": 9, "name": "wx_user_1", "key": "abc123", "created_time": 2},
                        ]
                    }
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def mock_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(dmx_client.httpx, "AsyncClient", mock_client)

    api_key = asyncio.run(dmx_client.create_user_token(name="wx_user_1", quota_yuan=10))
    assert api_key == "sk-abc123"
    assert posted == [
        {
            "name": "wx_user_1",
            "unlimited_quota": False,
            "remain_quota": 5_000_000,
            "unlimited_count": True,
            "remain_count": 0,
            "expired_time": -1,
            "group": "default",
            "model_limits_enabled": False,
            "model_limits": "",
            "allow_ips": "",
            "exclude_ips": "",
        }
    ]


def test_create_user_token_falls_back_to_search(monkeypatch) -> None:
    monkeypatch.setenv("DMX_SYSTEM_TOKEN", "admin-token")
    monkeypatch.setenv("DMX_API_USER_ID", "42")
    monkeypatch.setenv("DMX_API_BASE_URL", "https://dmx.example")

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/token/":
            return httpx.Response(200, json={"success": True})
        if request.method == "GET" and request.url.path == "/api/token/":
            return httpx.Response(200, json={"data": {"items": []}})
        if request.method == "GET" and request.url.path == "/api/token/search":
            assert request.url.params.get("keyword") == "wx_user_2"
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": 3, "name": "wx_user_2", "key": "search-key", "created_time": 1},
                    ]
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def mock_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(dmx_client.httpx, "AsyncClient", mock_client)

    api_key = asyncio.run(dmx_client.create_user_token(name="wx_user_2", quota_yuan=10))
    assert api_key == "sk-search-key"


def test_pick_token_key_rejects_masked_key() -> None:
    items = [
        {"id": 2, "name": "wx_user", "key": "sk-ab************cd", "created_time": 2},
        {"id": 1, "name": "wx_user", "key": "real-key", "created_time": 1},
    ]
    assert dmx_client._pick_token_key_for_name(items, "wx_user") == "sk-real-key"


def test_parse_token_items_supports_search_shape() -> None:
    payload = {"data": [{"name": "a", "key": "k1"}]}
    assert dmx_client._parse_token_items(payload) == [{"name": "a", "key": "k1"}]


def test_top_up_token_by_name_adds_remain_quota(monkeypatch) -> None:
    monkeypatch.setenv("DMX_SYSTEM_TOKEN", "admin-token")
    monkeypatch.setenv("DMX_API_USER_ID", "42")
    monkeypatch.setenv("DMX_API_BASE_URL", "https://dmx.example")
    put_body: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/token/":
            return httpx.Response(
                200,
                json={"data": {"items": [{"id": 99, "name": "wx_topup", "created_time": 1}]}},
            )
        if request.method == "GET" and request.url.path == "/api/token/99":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": 99,
                        "name": "wx_topup",
                        "remain_quota": 1_000_000,
                        "used_quota": 0,
                        "unlimited_quota": False,
                        "unlimited_count": True,
                        "remain_count": 0,
                        "expired_time": -1,
                        "group": "default",
                        "model_limits_enabled": False,
                        "model_limits": "",
                        "allow_ips": "",
                        "exclude_ips": "",
                    }
                },
            )
        if request.method == "PUT" and request.url.path == "/api/token/":
            put_body.append(json.loads(request.content.decode("utf-8")))
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "remain_quota": put_body[-1]["remain_quota"],
                        "used_quota": 0,
                        "unlimited_quota": False,
                    },
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def mock_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(dmx_client.httpx, "AsyncClient", mock_client)

    result = asyncio.run(dmx_client.top_up_token_by_name(name="wx_topup", add_yuan=10))
    assert put_body[0]["remain_quota"] == 6_000_000
    assert put_body[0]["unlimited_count"] is True
    assert result["add_yuan"] == 10
    assert result["remain_yuan"] == 12.0


def test_top_up_token_by_api_key_adds_remain_quota(monkeypatch) -> None:
    monkeypatch.setenv("DMX_SYSTEM_TOKEN", "admin-token")
    monkeypatch.setenv("DMX_API_USER_ID", "42")
    monkeypatch.setenv("DMX_API_BASE_URL", "https://dmx.example")
    put_body: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/token/key/sk-user-key":
            return httpx.Response(200, json={"data": {"id": 77, "name": "demo-user"}})
        if request.method == "GET" and request.url.path == "/api/token/77":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": 77,
                        "name": "demo-user",
                        "remain_quota": 0,
                        "used_quota": 5_000_000,
                        "unlimited_quota": False,
                        "unlimited_count": True,
                        "remain_count": 0,
                        "expired_time": -1,
                        "group": "default",
                        "model_limits_enabled": False,
                        "model_limits": "",
                        "allow_ips": "",
                        "exclude_ips": "",
                    }
                },
            )
        if request.method == "PUT" and request.url.path == "/api/token/":
            put_body.append(json.loads(request.content.decode("utf-8")))
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "remain_quota": put_body[-1]["remain_quota"],
                        "used_quota": 5_000_000,
                        "unlimited_quota": False,
                    },
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def mock_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(dmx_client.httpx, "AsyncClient", mock_client)

    result = asyncio.run(dmx_client.top_up_token_by_api_key(api_key="sk-user-key", add_yuan=10))
    assert put_body[0]["remain_quota"] == 5_000_000
    assert result["add_yuan"] == 10
    assert result["remain_yuan"] == 10.0
    assert result["exhausted"] is False


def test_get_token_balance_parses_remain_yuan(monkeypatch) -> None:
    monkeypatch.setenv("DMX_API_USER_ID", "42")
    monkeypatch.setenv("DMX_API_BASE_URL", "https://dmx.example")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/token/key/sk-test"
        return httpx.Response(
            200,
            json={
                "data": {
                    "remain_quota": 2_500_000,
                    "used_quota": 500_000,
                    "unlimited_quota": False,
                }
            },
        )

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def mock_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(dmx_client.httpx, "AsyncClient", mock_client)

    balance = asyncio.run(dmx_client.get_token_balance("sk-test"))
    assert balance["configured"] is True
    assert balance["remain_yuan"] == 5.0
    assert balance["used_yuan"] == 1.0
    assert balance["exhausted"] is False


def test_parse_balance_payload_marks_exhausted() -> None:
    payload = dmx_client.parse_balance_payload(
        {"remain_quota": 0, "used_quota": 5_000_000, "unlimited_quota": False}
    )
    assert payload["exhausted"] is True
    assert payload["remain_yuan"] == 0.0


def test_merge_platform_llm_defaults_preserves_admin_model(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_LLM_DEFAULT_MODEL", "deepseek-chat")
    monkeypatch.setenv("DMX_API_BASE_URL", "https://www.dmxapi.cn")
    merged = dmx_client.merge_platform_llm_defaults(
        {"model": "gpt-4o-mini", "api_key": "sk-x"}
    )
    assert merged["model"] == "gpt-4o-mini"
    assert merged["base_url"] == "https://www.dmxapi.cn"


def test_quota_units_to_yuan() -> None:
    assert dmx_client.quota_units_to_yuan(500_000) == 1.0
    assert dmx_client.quota_units_to_yuan(5_000_000) == 10.0


def test_voice_test_mode_enabled(monkeypatch) -> None:
    monkeypatch.delenv("SHUXIN_VOICE_TEST_MODE", raising=False)
    assert dmx_client.voice_test_mode_enabled() is False
    monkeypatch.setenv("SHUXIN_VOICE_TEST_MODE", "1")
    assert dmx_client.voice_test_mode_enabled() is True
