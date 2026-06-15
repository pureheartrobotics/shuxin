"""E2E 测试共用 helper（供 scripts 与 scenario_runner 引用）。"""

from __future__ import annotations

import json
import os
from typing import Any

E2E_TEST_TOKEN = "e2e-test-token"


def apply_demo_llm(device: Any) -> None:
    from shuxin.voice.config import LLMDeviceConfig

    device.llm = LLMDeviceConfig(
        provider=os.environ.get("DEMO_LLM_PROVIDER", "openai-compatible").strip()
        or "openai-compatible",
        model=os.environ.get("DEMO_LLM_MODEL", "").strip(),
        base_url=os.environ.get("DEMO_LLM_BASE_URL", "").strip(),
        api_key=os.environ.get("DEMO_LLM_API_KEY", "").strip(),
    )


def merge_device_llm(device: Any, settings: Any) -> None:
    from shuxin.voice.config import merge_llm_device_config

    if settings.llm_config:
        device.llm = merge_llm_device_config(device.llm, settings.llm_config)


def mem0_search(user_id: str, query: str) -> list[str]:
    from shuxin.core.config import get_shuxin_home
    from shuxin.core.memory import MemoryManager

    user_home = get_shuxin_home() / "users" / user_id / "memory"
    user_home.mkdir(parents=True, exist_ok=True)
    mem = MemoryManager(data_dir=str(user_home))
    return mem._search_mem0(query)


async def ensure_scenario_user(repo: Any, scenario: dict[str, Any]) -> None:
    user_id = scenario["user_id"]
    device_id = scenario.get("device_id", "demo-device-002")
    mbti = scenario.get("mbti", "INFJ")
    await repo.pool.execute(
        """
        INSERT INTO users (user_id, token, llm_config, enabled, metadata, updated_at)
        VALUES ($1, $2, '{}'::jsonb, true, $3::jsonb, now())
        ON CONFLICT (user_id) DO UPDATE SET
            token = EXCLUDED.token,
            enabled = true,
            deleted_at = NULL,
            updated_at = now()
        """,
        user_id,
        E2E_TEST_TOKEN,
        json.dumps({"e2e": True, "scenario": scenario.get("id", "")}, ensure_ascii=False),
    )
    await repo.pool.execute(
        """
        UPDATE devices
        SET enabled = true,
            deleted_at = NULL,
            status = 'provisioned',
            metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
                'mbti', $2::text,
                'mbti_status', 'locked'
            ),
            updated_at = now()
        WHERE device_id = $1
        """,
        device_id,
        mbti,
    )
    await _force_rebind_device(repo, user_id=user_id, device_id=device_id)


async def _force_rebind_device(repo: Any, *, user_id: str, device_id: str) -> None:
    """E2E 专用：设备若已绑其他用户，先解绑再绑定当前场景用户。"""
    row = await repo.pool.fetchrow(
        """
        SELECT binding_id, user_id
        FROM device_bindings
        WHERE device_id = $1 AND status = 'active'
        """,
        device_id,
    )
    if row is not None and str(row["user_id"]) != user_id:
        await repo.admin_unbind_device(binding_id=str(row["binding_id"]))
    await repo.admin_bind_device(user_id=user_id, device_id=device_id)
