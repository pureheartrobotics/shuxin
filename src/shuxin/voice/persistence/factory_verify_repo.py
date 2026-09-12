from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
import hmac
import json
import logging
import os
import random
import re
import secrets
import uuid
from pathlib import Path
from typing import Any, Optional

from shuxin.voice.config.payment_config import (
    DEFAULT_CREDIT_RATIO,
    DISPLAY_BALANCE_METADATA_KEY,
    PAYMENT_CREDIT_RATIO_SETTING_KEY,
    PaymentPlan,
    compute_payment_credits,
    normalize_credit_ratio,
    plan_from_row,
)
from shuxin.voice.persistence.time_display import format_beijing_display, format_beijing_iso
from shuxin.voice.integrations.dmx_client import (
    DEFAULT_QUOTA_YUAN,
    MAX_TOP_UP_YUAN,
    QUOTA_EXHAUSTED_MESSAGE,
    create_user_token,
    dmx_admin_configured,
    get_token_balance,
    merge_platform_llm_defaults,
    top_up_token_by_api_key,
    voice_test_mode_enabled,
)

logger = logging.getLogger("shuxin.voice.postgres")

import yaml

from shuxin.voice.audio.audio_files import compress_wav_to_mp3, purge_attachment_file, sha256_file
from shuxin.voice.persistence.device_secret_crypto import (
    device_secret_encryption_configured,
    encrypt_device_secret,
    mask_device_secret,
    require_device_secret_encryption,
    resolve_stored_device_secret,
)
from shuxin.voice.config.config import (
    DeviceConfig,
    LLMDeviceConfig,
    ProviderConfig,
    _expand_env,
    _merge_dict,
    default_device_tts_config,
    default_tencent_stt_config,
)
from shuxin.voice.persistence.memory_summary import (
    SUMMARY_WINDOW_DAYS,
    apply_turn_to_summary,
    finalize_summary_after_merge,
    merge_summary_with_llm,
    merge_summary_with_stats,
    memory_field_defaults,
    should_merge_summary,
    sync_summary_json,
)
from shuxin.core.identity import VALID_MBTI_TYPES
from shuxin.voice.persistence.agents import (
    DEFAULT_AGENT_ID,
    AgentRecord,
    cache_agent,
    get_cached_agent,
    invalidate_agent_cache,
)
from shuxin.voice.persistence.users import (
    DEFAULT_AUDIO_QUOTA_MB,
    DEFAULT_USER_ID,
    FACTORY_PROBE_USER_ID,
    UserSettings,
    validate_user_id,
)
from shuxin.voice.persistence.base_repo import (
    BaseRepository,
    _dt,
    _dt_iso,
    _json_obj,
    _payment_order_item,
    _device_row,
    _secret_unavailable_message,
    _sanitize_binding_metadata,
    _binding_row,
    _mask_secrets,
    _validate_device_code,
    _validate_claim_code,
    _search_pattern,
    _user_outputs_root,
    _validate_code_prefix,
    _make_device_id,
    _make_claim_code,
    _device_sequence,
    _hash_secret,
    _verify_hash,
    _verify_device_secret,
    _openid_from_wx_code,
)

COMPRESS_TARGET_RATIO = 0.8
DEVICE_CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")


class FactoryVerifyRepository(BaseRepository):
    async def factory_verify_lookup(self, claim_code: str) -> dict[str, Any]:
        """根据 claim_code 查询对应的 device_id；不锁行，只读。

        返回 device_id、claim_code_status、metadata 及解析后的 mbti 字段。
        若找不到则 raise ValueError。
        """
        selected_claim = _validate_claim_code(claim_code)
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT c.device_id, c.status AS claim_status, d.metadata
                FROM device_claim_codes c
                JOIN devices d ON d.device_id = c.device_id
                WHERE (c.claim_code = $1 OR c.claim_code_hash = $2)
                  AND d.enabled = true
                  AND d.deleted_at IS NULL
                  AND d.status <> 'disabled'
                ORDER BY c.created_at DESC
                LIMIT 1
                """,
                selected_claim,
                _hash_secret(selected_claim),
            )
        if row is None:
            raise ValueError(f"claim_code not found or device disabled: {claim_code!r}")
        metadata = _json_obj(row["metadata"])
        mbti = str(metadata.get("mbti") or "").strip().upper()
        mbti_status = str(metadata.get("mbti_status") or "").strip().lower()
        return {
            "device_id": str(row["device_id"]),
            "claim_code_status": str(row["claim_status"]),
            "metadata": metadata,
            "mbti": mbti,
            "mbti_status": mbti_status,
        }

    async def factory_verify_user_has_role(self, session_token: str) -> str:
        """校验 session_token 有效，并返回对应 user_id。

        若用户 metadata 中 factory_role 不为 'true'，raise PermissionError。
        """
        selected_token = str(session_token or "").strip()
        if not selected_token:
            raise PermissionError("session_token is required")
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT u.user_id, u.metadata
                FROM wechat_sessions s
                JOIN users u ON u.user_id = s.user_id
                WHERE s.session_token_hash = $1
                  AND s.expires_at > now()
                  AND u.enabled = true
                  AND u.deleted_at IS NULL
                """,
                _hash_secret(selected_token),
            )
        if row is None:
            raise PermissionError("session_token is invalid or expired")
        meta = _json_obj(row["metadata"])
        if str(meta.get("factory_role") or "").lower() != "true":
            raise PermissionError("user does not have factory_role")
        return str(row["user_id"])

    async def factory_verify_log(
        self,
        *,
        verify_id: str,
        claim_code: str,
        device_id: str,
        operator_user: str,
        result: str,
        fail_reason: str = "",
        meta: dict[str, Any] | None = None,
    ) -> None:
        """写入一条验收日志（PASS 或 FAIL）。"""
        await self.pool.execute(
            """
            INSERT INTO factory_verify_logs
                (verify_id, claim_code, device_id, operator_user,
                 result, fail_reason, meta)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
            ON CONFLICT (verify_id) DO NOTHING
            """,
            verify_id,
            str(claim_code),
            str(device_id),
            str(operator_user),
            str(result),
            str(fail_reason),
            json.dumps(meta or {}, ensure_ascii=False),
        )

    async def factory_verify_logs_list(
        self,
        *,
        operator_user: str = "",
        device_id: str = "",
        limit: int = 50,
        retention_days: int = 0,
    ) -> list[dict[str, Any]]:
        """查询验收日志，按时间倒序。"""
        retention_clause = ""
        params: list[Any] = [str(operator_user or ""), str(device_id or "")]
        if retention_days > 0:
            retention_clause = "AND verified_at >= now() - make_interval(days => $3)"
            params.append(int(retention_days))
            limit_param = "$4"
        else:
            limit_param = "$3"
        params.append(int(limit))
        rows = await self.pool.fetch(
            f"""
            SELECT verify_id, claim_code, device_id, operator_user,
                   result, fail_reason, verified_at, meta
            FROM factory_verify_logs
            WHERE ($1::text = '' OR operator_user = $1)
              AND ($2::text = '' OR device_id = $2)
              {retention_clause}
            ORDER BY verified_at DESC
            LIMIT {limit_param}
            """,
            *params,
        )
        return [
            {
                "verify_id": str(r["verify_id"]),
                "claim_code": str(r["claim_code"]),
                "device_id": str(r["device_id"]),
                "operator_user": str(r["operator_user"]),
                "result": str(r["result"]),
                "fail_reason": str(r["fail_reason"]),
                "verified_at": _dt(r["verified_at"]) if r["verified_at"] else None,
                "meta": _json_obj(r["meta"]),
            }
            for r in rows
        ]

    async def purge_expired_factory_verify_logs(self, *, retention_days: int) -> dict[str, int]:
        if retention_days <= 0:
            return {"purged": 0}
        result = await self.pool.execute(
            """
            DELETE FROM factory_verify_logs
            WHERE verified_at < now() - make_interval(days => $1)
            """,
            int(retention_days),
        )
        purged = 0
        parts = str(result or "").split()
        if len(parts) == 2 and parts[0] == "DELETE":
            purged = int(parts[1])
        return {"purged": purged}
