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


class MbtiRepository(BaseRepository):
    async def _attach_mbti_reveal_on_bind(
        self,
        conn,
        device_id: str,
    ) -> dict[str, Any] | None:
        reveal = await self._try_reveal_and_lock_conn(conn, device_id, "miniprogram_bind")
        if reveal:
            return reveal
        row = await conn.fetchrow(
            """
            SELECT metadata
            FROM devices
            WHERE device_id = $1 AND deleted_at IS NULL
            """,
            device_id,
        )
        if row is None:
            return None
        from shuxin.voice.config.mbti_reveal import build_mbti_client_payload, is_mbti_locked

        metadata = _json_obj(row["metadata"])
        if is_mbti_locked(metadata):
            return build_mbti_client_payload(metadata, is_first_reveal=False)
        return None

    async def _try_reveal_and_lock_conn(
        self,
        conn,
        device_id: str,
        revealed_by: str,
    ) -> dict[str, Any] | None:
        row = await conn.fetchrow(
            """
            SELECT metadata
            FROM devices
            WHERE device_id = $1 AND deleted_at IS NULL
            FOR UPDATE
            """,
            device_id,
        )
        if row is None:
            return None
        metadata = _json_obj(row["metadata"])
        from shuxin.voice.config.mbti_reveal import build_mbti_client_payload, needs_mbti_reveal

        if not needs_mbti_reveal(metadata):
            return None

        await conn.execute(
            """
            UPDATE devices
            SET metadata = COALESCE(metadata, '{}'::jsonb)
                || jsonb_build_object('mbti_status', 'locked')
                || jsonb_build_object('mbti_revealed_by', $2::text)
                || jsonb_build_object(
                    'mbti_revealed_at',
                    to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
                )
                || jsonb_build_object('device_intro_played', false),
                updated_at = now()
            WHERE device_id = $1
            """,
            device_id,
            revealed_by,
        )
        updated = {
            **metadata,
            "mbti_status": "locked",
            "device_intro_played": False,
        }
        return build_mbti_client_payload(updated, is_first_reveal=True)

    async def try_reveal_and_lock(self, device_id: str, revealed_by: str) -> dict[str, Any] | None:
        selected_id = _validate_device_code(device_id)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                result = await self._try_reveal_and_lock_conn(conn, selected_id, revealed_by)
                if result:
                    await self.parent.audit(
                        "mbti_reveal_locked",
                        "device",
                        selected_id,
                        {"revealed_by": revealed_by, "mbti": result.get("mbti")},
                    )
                return result

    async def mark_device_intro_played(self, device_id: str) -> dict[str, Any]:
        selected_id = _validate_device_code(device_id)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                result = await conn.execute(
                    """
                    UPDATE devices
                    SET metadata = COALESCE(metadata, '{}'::jsonb)
                        || jsonb_build_object('device_intro_played', true),
                        updated_at = now()
                    WHERE device_id = $1 AND deleted_at IS NULL
                    """,
                    selected_id,
                )
                if not result.endswith("1"):
                    raise PermissionError("device is disabled or not found")
        return {"device_id": selected_id, "device_intro_played": True}

    async def update_device_mbti(self, device_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        selected_id = _validate_device_code(device_id)
        mbti = str(payload.get("mbti") or "").strip().upper()
        if not mbti or mbti not in VALID_MBTI_TYPES:
            raise ValueError(f"invalid mbti: {mbti}")

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                result = await conn.execute(
                    """
                    UPDATE devices
                    SET metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object('mbti', $2::text),
                        updated_at = now()
                    WHERE device_id = $1 AND deleted_at IS NULL
                    """,
                    selected_id,
                    mbti,
                )
                if not result.endswith("1"):
                    raise PermissionError("device is disabled or not found")

                await self.parent.audit(
                    "update_device_mbti",
                    "device",
                    selected_id,
                    {"mbti": mbti},
                )

        return {"device_id": selected_id, "mbti": mbti}

    async def mark_mbti_locked(self, device_id: str) -> dict[str, Any]:
        selected_id = _validate_device_code(device_id)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                result = await conn.execute(
                    """
                    UPDATE devices
                    SET metadata = COALESCE(metadata, '{}'::jsonb)
                        || jsonb_build_object('mbti_status', 'locked')
                        || jsonb_build_object('mbti_revealed_at', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')),
                        updated_at = now()
                    WHERE device_id = $1 AND deleted_at IS NULL
                    """,
                    selected_id,
                )
                if not result.endswith("1"):
                    raise PermissionError("device is disabled or not found")
                await self.parent.audit(
                    "mark_mbti_locked",
                    "device",
                    selected_id,
                    {},
                )
        return {"device_id": selected_id, "mbti_status": "locked"}
