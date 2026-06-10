"""DMXAPI token provisioning and balance queries."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("shuxin.voice.dmx")

QUOTA_UNITS_PER_YUAN = 500_000
DEFAULT_QUOTA_YUAN = 10.0
MAX_TOP_UP_YUAN = 1000.0
QUOTA_EXHAUSTED_MESSAGE = "额度已用尽，请联系客服"


def voice_test_mode_enabled() -> bool:
    return os.environ.get("SHUXIN_VOICE_TEST_MODE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def dmx_admin_configured() -> bool:
    return bool(
        os.environ.get("DMX_SYSTEM_TOKEN", "").strip()
        and os.environ.get("DMX_API_USER_ID", "").strip()
    )


def default_platform_llm_config() -> dict[str, str]:
    base_url = os.environ.get("DMX_API_BASE_URL", "https://www.dmxapi.cn").strip()
    return {
        "provider": os.environ.get("SHUXIN_LLM_DEFAULT_PROVIDER", "openai-compatible").strip()
        or "openai-compatible",
        "model": os.environ.get("SHUXIN_LLM_DEFAULT_MODEL", "deepseek-chat").strip()
        or "deepseek-chat",
        "base_url": base_url or "https://www.dmxapi.cn",
    }


def merge_platform_llm_defaults(existing: dict[str, Any] | None) -> dict[str, Any]:
    """Fill missing model/base_url/provider without overwriting admin overrides."""
    merged = dict(existing or {})
    for key, value in default_platform_llm_config().items():
        if not str(merged.get(key) or "").strip():
            merged[key] = value
    return merged


def quota_units_to_yuan(units: int | float) -> float:
    return round(float(units) / QUOTA_UNITS_PER_YUAN, 4)


def _dmx_api_root() -> str:
    return os.environ.get("DMX_API_BASE_URL", "https://www.dmxapi.cn").rstrip("/")


def _admin_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {os.environ['DMX_SYSTEM_TOKEN'].strip()}",
        "Rix-Api-User": os.environ["DMX_API_USER_ID"].strip(),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _normalize_api_key(raw: str) -> str:
    selected = str(raw or "").strip()
    if not selected:
        return ""
    return selected if selected.startswith("sk-") else f"sk-{selected}"


def _is_usable_api_key(raw: str) -> bool:
    key = _normalize_api_key(raw)
    return bool(key) and "*" not in key


def _parse_token_items(payload: Any) -> list[dict[str, Any]]:
    """Normalize DMX list/search responses to a flat token list."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    data = payload.get("data")
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]

    items = payload.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    return []


def _token_sort_key(item: dict[str, Any]) -> tuple[int, int]:
    token_id = int(item.get("id") or 0)
    created = int(item.get("created_time") or 0)
    return token_id, created


def _pick_token_key_for_name(items: list[dict[str, Any]], name: str) -> str:
    matches = [item for item in items if str(item.get("name") or "") == name]
    if not matches:
        return ""
    for item in sorted(matches, key=_token_sort_key, reverse=True):
        key = _normalize_api_key(str(item.get("key") or ""))
        if _is_usable_api_key(key):
            return key
    return ""


def _pick_latest_token_item(items: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    matches = [item for item in items if str(item.get("name") or "") == name]
    if not matches:
        return None
    return sorted(matches, key=_token_sort_key, reverse=True)[0]


async def _find_token_item_by_name(
    client: httpx.AsyncClient,
    name: str,
) -> dict[str, Any] | None:
    list_response = await client.get(
        f"{_dmx_api_root()}/api/token/",
        headers=_admin_headers(),
    )
    list_response.raise_for_status()
    selected = _pick_latest_token_item(_parse_token_items(list_response.json()), name)
    if selected is not None:
        return selected

    search_response = await client.get(
        f"{_dmx_api_root()}/api/token/search",
        headers=_admin_headers(),
        params={"keyword": name},
    )
    search_response.raise_for_status()
    return _pick_latest_token_item(_parse_token_items(search_response.json()), name)


async def _get_token_record(client: httpx.AsyncClient, token_id: int) -> dict[str, Any]:
    response = await client.get(
        f"{_dmx_api_root()}/api/token/{int(token_id)}",
        headers=_admin_headers(),
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        raise PermissionError("DMX token record response is invalid")
    return data


async def _fetch_token_key_by_name(client: httpx.AsyncClient, name: str) -> str:
    list_response = await client.get(
        f"{_dmx_api_root()}/api/token/",
        headers=_admin_headers(),
    )
    list_response.raise_for_status()
    key = _pick_token_key_for_name(_parse_token_items(list_response.json()), name)
    if key:
        return key

    search_response = await client.get(
        f"{_dmx_api_root()}/api/token/search",
        headers=_admin_headers(),
        params={"keyword": name},
    )
    search_response.raise_for_status()
    return _pick_token_key_for_name(_parse_token_items(search_response.json()), name)


def parse_balance_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    unlimited = bool(payload.get("unlimited_quota"))
    remain_units = int(payload.get("remain_quota") or 0)
    used_units = int(payload.get("used_quota") or 0)
    remain_yuan = None if unlimited else quota_units_to_yuan(remain_units)
    used_yuan = quota_units_to_yuan(used_units)
    exhausted = not unlimited and remain_units <= 0
    return {
        "remain_yuan": remain_yuan,
        "used_yuan": used_yuan,
        "unlimited_quota": unlimited,
        "exhausted": exhausted,
        "configured": True,
    }


async def create_user_token(*, name: str, quota_yuan: float = DEFAULT_QUOTA_YUAN) -> str:
    """Create a DMX user token and return the sk- API key."""
    if not dmx_admin_configured():
        raise PermissionError("DMX admin credentials are not configured")

    amount = max(0.0, float(quota_yuan))
    body = {
        "name": name,
        "unlimited_quota": False,
        "remain_quota": int(amount * QUOTA_UNITS_PER_YUAN),
        "unlimited_count": True,
        "remain_count": 0,
        "expired_time": -1,
        "group": "default",
        "model_limits_enabled": False,
        "model_limits": "",
        "allow_ips": "",
        "exclude_ips": "",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{_dmx_api_root()}/api/token/",
            headers=_admin_headers(),
            json=body,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("success") is False:
            raise PermissionError(str(payload.get("message") or "DMX token create failed"))

        key = await _fetch_token_key_by_name(client, name)
        if key:
            return key

    raise PermissionError(f"DMX token created but key not found for name={name}")


async def top_up_token_by_name(*, name: str, add_yuan: float) -> dict[str, Any]:
    """Increment a DMX token balance by add_yuan (yuan)."""
    if not dmx_admin_configured():
        raise PermissionError("DMX admin credentials are not configured")

    amount = float(add_yuan)
    if amount <= 0:
        raise ValueError("add_yuan must be positive")
    if amount > MAX_TOP_UP_YUAN:
        raise ValueError(f"add_yuan must not exceed {MAX_TOP_UP_YUAN}")

    added_units = int(amount * QUOTA_UNITS_PER_YUAN)
    async with httpx.AsyncClient(timeout=30.0) as client:
        item = await _find_token_item_by_name(client, name)
        if item is None:
            raise PermissionError(f"DMX token not found for name={name}")

        token_id = int(item.get("id") or 0)
        if token_id <= 0:
            raise PermissionError(f"DMX token id is invalid for name={name}")

        current = await _get_token_record(client, token_id)
        if bool(current.get("unlimited_quota")):
            raise PermissionError("DMX token has unlimited quota; incremental top-up is not supported")

        current["remain_quota"] = int(current.get("remain_quota") or 0) + added_units
        current["unlimited_quota"] = False
        current["unlimited_count"] = True
        current["remain_count"] = 0

        response = await client.put(
            f"{_dmx_api_root()}/api/token/",
            headers=_admin_headers(),
            json=current,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("success") is False:
            raise PermissionError(str(payload.get("message") or "DMX token top-up failed"))

        updated = payload.get("data") if isinstance(payload.get("data"), dict) else current
        result = parse_balance_payload(updated if isinstance(updated, dict) else current)
        result["add_yuan"] = amount
        logger.info("DMX topped up %s by %s yuan", name, amount)
        return result


async def get_token_balance(api_key: str) -> dict[str, Any]:
    selected = _normalize_api_key(api_key)
    if not selected:
        return {
            "remain_yuan": None,
            "used_yuan": None,
            "unlimited_quota": False,
            "exhausted": False,
            "configured": False,
        }
    if not os.environ.get("DMX_API_USER_ID", "").strip():
        return {
            "remain_yuan": None,
            "used_yuan": None,
            "unlimited_quota": False,
            "exhausted": False,
            "configured": False,
        }

    headers = {
        "Accept": "application/json",
        "Rix-Api-User": os.environ["DMX_API_USER_ID"].strip(),
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{_dmx_api_root()}/api/token/key/{selected}",
            headers=headers,
        )
        response.raise_for_status()
        return parse_balance_payload(response.json())
