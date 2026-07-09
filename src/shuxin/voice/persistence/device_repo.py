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


class DeviceRepository(BaseRepository):
    async def provision_device(self, device_code: str) -> dict[str, Any]:
        """工厂烧录时登记设备，并生成只给用户扫码认领用的 claim_code。"""
        require_device_secret_encryption()
        selected_code = _validate_device_code(device_code)
        device_secret = secrets.token_urlsafe(32)
        claim_code = _make_claim_code("CLM", "A001", _device_sequence(selected_code) or 1)
        qr_base = os.environ.get("SHUXIN_MINIPROGRAM_BIND_PATH", "/pages/index/index")
        qr_payload = f"{qr_base}?claim_code={claim_code}"

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await self._insert_provisioned_device(
                    conn,
                    device_id=selected_code,
                    device_secret=device_secret,
                    claim_code=claim_code,
                    note="factory provisioned device",
                    metadata={
                        "provisioned_by": "factory",
                        "mbti": random.choice(sorted(VALID_MBTI_TYPES)),
                        "mbti_status": "sealed",
                    },
                )

        return {
            "device_code": selected_code,
            "device_id": selected_code,
            "device_secret": device_secret,
            "claim_code": claim_code,
            "qr_payload": qr_payload,
            "auth_mode": "per_device_secret",
        }

    async def provision_devices_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        require_device_secret_encryption()
        device_prefix = _validate_code_prefix(str(payload.get("device_prefix") or "SX"))
        label_prefix = _validate_code_prefix(str(payload.get("label_prefix") or "CLM"))
        label_batch = _validate_code_prefix(str(payload.get("label_batch") or "A001"))
        start = max(1, int(payload.get("device_start") or 1))
        quantity = max(1, min(int(payload.get("quantity") or 1), 500))
        note = str(payload.get("note") or "factory batch provisioned device")
        qr_base = os.environ.get("SHUXIN_MINIPROGRAM_BIND_PATH", "/pages/index/index")
        items: list[dict[str, Any]] = []

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for offset in range(quantity):
                    sequence = start + offset
                    device_id = _make_device_id(device_prefix, sequence)
                    claim_code = _make_claim_code(label_prefix, label_batch, sequence)
                    exists = await conn.fetchval(
                        """
                        SELECT 1
                        FROM devices
                        WHERE device_id = $1 AND deleted_at IS NULL
                        """,
                        device_id,
                    )
                    if exists:
                        raise ValueError(f"device_id already exists: {device_id}")
                    device_secret = secrets.token_urlsafe(32)
                    blind_mbti = random.choice(sorted(VALID_MBTI_TYPES))
                    await self._insert_provisioned_device(
                        conn,
                        device_id=device_id,
                        device_secret=device_secret,
                        claim_code=claim_code,
                        note=note,
                        metadata={
                            "provisioned_by": "admin_batch",
                            "label_batch": label_batch,
                            "sequence": sequence,
                            "mbti": blind_mbti,
                            "mbti_status": "sealed",
                        },
                    )
                    items.append(
                        {
                            "device_id": device_id,
                            "device_code": device_id,
                            "device_secret": device_secret,
                            "claim_code": claim_code,
                            "qr_payload": f"{qr_base}?claim_code={claim_code}",
                            "barcode_url": f"/admin/api/claim-codes/{claim_code}/barcode.png",
                            "auth_mode": "per_device_secret",
                            "mbti": blind_mbti,
                        }
                    )
        return {"items": items}

    async def next_device_sequence(self, device_prefix: str) -> dict[str, Any]:
        prefix = _validate_code_prefix(device_prefix or "SX")
        pattern = f"^{re.escape(prefix)}-[0-9]{{6}}$"
        async with self.pool.acquire() as conn:
            next_sequence = await conn.fetchval(
                """
                SELECT COALESCE(MAX(substring(device_id from '[0-9]+$')::integer), 0) + 1
                FROM devices
                WHERE device_id LIKE $1
                  AND device_id ~ $2
                """,
                f"{prefix}-%",
                pattern,
            )
        return {
            "device_prefix": prefix,
            "next_sequence": int(next_sequence or 1),
            "next_device_id": _make_device_id(prefix, int(next_sequence or 1)),
        }

    async def _insert_provisioned_device(
        self,
        conn,
        *,
        device_id: str,
        device_secret: str,
        claim_code: str,
        note: str,
        metadata: dict[str, Any],
    ) -> None:
        stt_config = json.dumps(default_tencent_stt_config(), ensure_ascii=False)
        tts_config = json.dumps(default_device_tts_config(), ensure_ascii=False)
        await conn.execute(
            """
            INSERT INTO devices (
                device_id, auth_mode, device_secret_hash, device_secret_encrypted,
                stt_config, tts_config,
                status, enabled, note, metadata, updated_at
            )
            VALUES (
                $1, 'per_device_secret', $2, $3, $4::jsonb, $5::jsonb,
                'provisioned', true, $6, $7::jsonb, now()
            )
            ON CONFLICT (device_id) DO UPDATE SET
                auth_mode = 'per_device_secret',
                device_secret_hash = excluded.device_secret_hash,
                device_secret_encrypted = excluded.device_secret_encrypted,
                status = CASE
                    WHEN devices.status = 'disabled' THEN 'disabled'
                    ELSE devices.status
                END,
                note = excluded.note,
                metadata = devices.metadata || excluded.metadata,
                deleted_at = NULL,
                updated_at = now()
            """,
            device_id,
            _hash_secret(device_secret),
            encrypt_device_secret(device_secret),
            stt_config,
            tts_config,
            note,
            json.dumps(metadata, ensure_ascii=False),
        )
        await conn.execute(
            "INSERT INTO device_status (device_id) VALUES ($1) ON CONFLICT (device_id) DO NOTHING",
            device_id,
        )
        await conn.execute(
            """
            UPDATE device_claim_codes
            SET status = 'revoked'
            WHERE device_id = $1 AND status = 'active'
            """,
            device_id,
        )
        await conn.execute(
            """
            INSERT INTO device_claim_codes (
                claim_code_id, device_id, claim_code, claim_code_hash, status
            )
            VALUES ($1, $2, $3, $4, 'active')
            """,
            uuid.uuid4().hex,
            device_id,
            claim_code,
            _hash_secret(claim_code),
        )
        await self._record_binding_event(
            conn,
            event_type="device_provisioned",
            device_id=device_id,
            metadata={"auth_mode": "per_device_secret", "claim_code": claim_code},
        )

    async def bind_device(
        self,
        *,
        wx_code: str,
        session_token: str = "",
        claim_code: str = "",
        device_code: str = "",
    ) -> dict[str, Any]:
        """小程序扫码绑定: wx_code -> openid，claim_code 或 device_code -> device。"""
        user_id = ""
        selected_claim = str(claim_code or "").strip()
        selected_device = str(device_code or "").strip()
        if not selected_claim and not selected_device:
            raise ValueError("claim_code or device_code is required")

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                user_id = await self.parent._user_id_from_wechat_auth(
                    conn,
                    session_token=session_token,
                    wx_code=wx_code,
                )
                await conn.execute(
                    """
                    INSERT INTO users (user_id, metadata, updated_at)
                    VALUES ($1, $2::jsonb, now())
                    ON CONFLICT (user_id) DO UPDATE SET
                        deleted_at = NULL,
                        enabled = true,
                        updated_at = now()
                    """,
                    user_id,
                    json.dumps({"identity_provider": "wechat"}, ensure_ascii=False),
                )
                claim_id = None
                if selected_claim:
                    claim = await self._find_active_claim(conn, selected_claim)
                    if claim is None:
                        status = await self._find_claim_status(conn, selected_claim)
                        if status:
                            raise PermissionError("claim_code is already claimed or inactive")
                        raise PermissionError("claim_code is invalid")
                    selected_device = str(claim["device_id"])
                    claim_id = str(claim["claim_code_id"])
                else:
                    selected_device = _validate_device_code(selected_device)
                    device_exists = await conn.fetchval(
                        """
                        SELECT 1
                        FROM devices
                        WHERE device_id = $1
                          AND enabled = true
                          AND deleted_at IS NULL
                          AND status <> 'disabled'
                        FOR UPDATE
                        """,
                        selected_device,
                    )
                    if not device_exists:
                        claim = await self._find_active_claim(conn, selected_device)
                        if claim is None:
                            status = await self._find_claim_status(conn, selected_device)
                            if status:
                                raise PermissionError("claim_code is already claimed or inactive")
                            raise PermissionError("claim_code or device_code is invalid")
                        selected_device = str(claim["device_id"])
                        claim_id = str(claim["claim_code_id"])

                result = await self._bind_device_for_user(
                    conn,
                    user_id=user_id,
                    device_id=selected_device,
                    event_type="device_bound_by_miniprogram",
                )
                if claim_id:
                    await conn.execute(
                        """
                        UPDATE device_claim_codes
                        SET status = 'claimed', claimed_at = now()
                        WHERE claim_code_id = $1
                        """,
                        claim_id,
                    )
        await self.parent.ensure_user_dmx_llm(user_id)
        return result

    async def _find_active_claim(self, conn, claim_code: str):
        selected_claim = _validate_claim_code(claim_code)
        return await conn.fetchrow(
            """
            SELECT c.claim_code_id, c.device_id
            FROM device_claim_codes c
            JOIN devices d ON d.device_id = c.device_id
            WHERE (c.claim_code = $1 OR c.claim_code_hash = $2)
              AND c.status = 'active'
              AND d.enabled = true
              AND d.deleted_at IS NULL
              AND d.status <> 'disabled'
            FOR UPDATE
            """,
            selected_claim,
            _hash_secret(selected_claim),
        )

    async def _find_claim_status(self, conn, claim_code: str) -> str:
        try:
            selected_claim = _validate_claim_code(claim_code)
        except ValueError:
            return ""
        value = await conn.fetchval(
            """
            SELECT status
            FROM device_claim_codes
            WHERE claim_code = $1 OR claim_code_hash = $2
            ORDER BY created_at DESC
            LIMIT 1
            """,
            selected_claim,
            _hash_secret(selected_claim),
        )
        return str(value or "")

    async def _user_id_from_wechat_auth(
        self,
        conn,
        *,
        session_token: str = "",
        wx_code: str = "",
    ) -> str:
        selected_token = str(session_token or "").strip()
        if selected_token:
            user_id = await conn.fetchval(
                """
                SELECT user_id
                FROM wechat_sessions
                WHERE session_token_hash = $1
                  AND expires_at > now()
                """,
                _hash_secret(selected_token),
            )
            if not user_id:
                raise PermissionError("session_token is invalid or expired")
            return validate_user_id(str(user_id))
        return validate_user_id(await _openid_from_wx_code(wx_code))

    async def _bind_device_for_user(
        self,
        conn,
        *,
        user_id: str,
        device_id: str,
        event_type: str,
    ) -> dict[str, Any]:
        existing = await conn.fetchrow(
            """
            SELECT binding_id, user_id
            FROM device_bindings
            WHERE device_id = $1 AND status = 'active'
            FOR UPDATE
            """,
            device_id,
        )
        if existing is not None:
            existing_user = str(existing["user_id"])
            if existing_user != user_id:
                await self._record_binding_event(
                    conn,
                    event_type="bind_rejected_already_bound",
                    user_id=user_id,
                    device_id=device_id,
                    metadata={"existing_user_id": existing_user},
                )
                raise PermissionError("device is already bound")
            result = {
                "binding_id": str(existing["binding_id"]),
                "user_id": user_id,
                "device_code": device_id,
                "already_bound": True,
            }
            mbti = await self.parent._attach_mbti_reveal_on_bind(conn, device_id)
            if mbti:
                result["mbti"] = mbti
            return result

        binding_id = uuid.uuid4().hex
        
        # Check if the device is being bound/activated for the first time
        is_first_activation = False
        device_row = await conn.fetchrow("SELECT status FROM devices WHERE device_id = $1", device_id)
        if device_row and device_row["status"] == "provisioned":
            is_first_activation = True

        await conn.execute(
            """
            INSERT INTO device_bindings (binding_id, user_id, device_id, status)
            VALUES ($1, $2, $3, 'active')
            """,
            binding_id,
            user_id,
            device_id,
        )
        await conn.execute(
            """
            UPDATE devices
            SET status = 'bound', updated_at = now()
            WHERE device_id = $1
            """,
            device_id,
        )

        if is_first_activation:
            await self.parent._apply_first_activation_gift(conn, device_id)

        await self._record_binding_event(
            conn,
            event_type=event_type,
            user_id=user_id,
            device_id=device_id,
            metadata={},
        )
        result = {
            "binding_id": binding_id,
            "user_id": user_id,
            "device_code": device_id,
            "already_bound": False,
        }
        mbti = await self.parent._attach_mbti_reveal_on_bind(conn, device_id)
        if mbti:
            result["mbti"] = mbti
        self._clear_auth_cache(device_id)
        return result

    async def authenticate_device(
        self,
        device_code: str | None,
        device_secret: str | None,
    ) -> UserSettings:
        """设备 hello 鉴权，并解析当前 active binding 对应的用户。"""
        selected_code = _validate_device_code(device_code or "")
        import time

        # Check in-memory cache
        cached = getattr(self, "_auth_cache", {}).get(selected_code)
        if cached:
            cached_row_dict, user_settings, expire_time = cached
            if time.time() < expire_time:
                if self.parent._verify_device_secret(cached_row_dict, device_secret or ""):
                    logger.info("Cache hit for device authentication: %s", selected_code)
                    return user_settings

        row = await self.pool.fetchrow(
            """
            SELECT d.device_id, d.auth_mode, d.device_secret_hash, b.user_id,
                   u.audio_quota_mb, u.llm_config, u.agent_id
            FROM devices d
            JOIN device_bindings b ON b.device_id = d.device_id AND b.status = 'active'
            JOIN users u ON u.user_id = b.user_id AND u.enabled = true AND u.deleted_at IS NULL
            WHERE d.device_id = $1
              AND d.enabled = true
              AND d.deleted_at IS NULL
              AND d.status <> 'disabled'
            """,
            selected_code,
        )
        if row is None:
            raise PermissionError("device is not bound or disabled")

        if not self.parent._verify_device_secret(row, device_secret or ""):
            await self._record_auth_failure(selected_code)
            raise PermissionError("invalid device secret")

        user_id = str(row["user_id"])
        await self.parent.ensure_user_dmx_llm(user_id)
        llm_row = await self.pool.fetchrow(
            "SELECT llm_config FROM users WHERE user_id = $1 AND deleted_at IS NULL",
            user_id,
        )
        llm_config = _json_obj(llm_row["llm_config"]) if llm_row else _json_obj(row["llm_config"])

        user_settings = UserSettings(
            user_id=user_id,
            token="",
            audio_quota_mb=int(row["audio_quota_mb"]),
            llm_config=llm_config,
            agent_id=str(row["agent_id"] or ""),
        )

        # Cache the result for 300 seconds (5 minutes)
        if hasattr(self, "_auth_cache"):
            self._auth_cache[selected_code] = (dict(row), user_settings, time.time() + 300)

        return user_settings

    async def authenticate_device_for_factory(
        self,
        device_code: str | None,
        device_secret: str | None,
    ) -> UserSettings:
        """未绑定且 provisioned 设备的工厂验收 hello 鉴权。"""
        selected_code = _validate_device_code(device_code or "")
        row = await self.pool.fetchrow(
            """
            SELECT d.device_id, d.auth_mode, d.device_secret_hash, d.status,
                   EXISTS(
                       SELECT 1 FROM device_bindings b
                       WHERE b.device_id = d.device_id AND b.status = 'active'
                   ) AS has_active_binding
            FROM devices d
            WHERE d.device_id = $1
              AND d.enabled = true
              AND d.deleted_at IS NULL
              AND d.status <> 'disabled'
            """,
            selected_code,
        )
        if row is None:
            raise PermissionError("device not found or disabled")
        if bool(row["has_active_binding"]):
            raise PermissionError("device already bound")
        if str(row["status"]) != "provisioned":
            raise PermissionError("device not in provisioned state")
        if not self.parent._verify_device_secret(row, device_secret or ""):
            await self._record_auth_failure(selected_code)
            raise PermissionError("invalid device secret")
        return UserSettings(
            user_id=FACTORY_PROBE_USER_ID,
            token="",
            audio_quota_mb=DEFAULT_AUDIO_QUOTA_MB,
            llm_config={},
            agent_id="",
        )

    async def unbind_device(self, *, user_id: str, device_code: str) -> dict[str, Any]:
        """用户主动解绑设备；保留用户级记忆和资产。"""
        selected_user = validate_user_id(user_id)
        selected_device = _validate_device_code(device_code)
        return await self._unbind_active_device(selected_user, selected_device, event_type="device_unbound")

    async def list_my_devices(self, *, wx_code: str, session_token: str = "") -> dict[str, Any]:
        """小程序端按 wx_code 解析当前用户并列出已绑定设备。"""
        async with self.pool.acquire() as conn:
            user_id = await self.parent._user_id_from_wechat_auth(
                conn,
                session_token=session_token,
                wx_code=wx_code,
            )
            rows = await conn.fetch(
                """
                SELECT b.binding_id, b.user_id, b.device_id, b.status, b.bound_at,
                       d.enabled, d.note, d.metadata,
                       s.online, s.last_seen, s.current_session_id, s.last_error
                FROM device_bindings b
                JOIN devices d ON d.device_id = b.device_id
                LEFT JOIN device_status s ON s.device_id = b.device_id
                WHERE b.user_id = $1 AND b.status = 'active' AND d.deleted_at IS NULL
                ORDER BY b.bound_at DESC, b.binding_id DESC
                """,
                user_id,
            )
        return {"user_id": user_id, "items": [_binding_row(row) for row in rows]}

    async def unbind_device_by_wx_code(
        self,
        *,
        wx_code: str,
        device_code: str,
    ) -> dict[str, Any]:
        """小程序端解绑当前 openid 名下的设备。"""
        user_id = validate_user_id(await _openid_from_wx_code(wx_code))
        selected_device = _validate_device_code(device_code)
        return await self._unbind_active_device(
            user_id,
            selected_device,
            event_type="device_unbound_by_miniprogram",
        )

    async def unbind_device_by_session(
        self,
        *,
        session_token: str,
        device_code: str,
    ) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            user_id = await self.parent._user_id_from_wechat_auth(
                conn,
                session_token=session_token,
                wx_code="",
            )
        selected_device = _validate_device_code(device_code)
        return await self._unbind_active_device(
            user_id,
            selected_device,
            event_type="device_unbound_by_miniprogram",
        )

    async def list_bindings(self, *, limit: int = 50, cursor: str = "", q: str = "") -> dict[str, Any]:
        search = _search_pattern(q)
        rows = await self.pool.fetch(
            """
            SELECT b.binding_id, b.user_id, b.device_id, b.status, b.bound_at,
                   d.enabled, d.note, d.metadata,
                   s.online, s.last_seen, s.current_session_id, s.last_error
            FROM device_bindings b
            JOIN devices d ON d.device_id = b.device_id
            LEFT JOIN device_status s ON s.device_id = b.device_id
            WHERE b.status = 'active'
              AND ($1 = '' OR b.binding_id > $1)
              AND ($3 = '' OR b.binding_id ILIKE $3 OR b.user_id ILIKE $3 OR b.device_id ILIKE $3)
            ORDER BY b.binding_id ASC
            LIMIT $2
            """,
            cursor,
            max(1, min(limit, 100)),
            search,
        )
        items = [_binding_row(row) for row in rows]
        return {
            "items": items,
            "next_cursor": items[-1]["binding_id"] if len(items) == limit else "",
        }

    async def admin_bind_device(self, *, user_id: str, device_id: str) -> dict[str, Any]:
        """后台手动绑定用户和设备，用于测试与客服处理。"""
        selected_user = validate_user_id(user_id)
        selected_device = _validate_device_code(device_id)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                user_exists = await conn.fetchval(
                    """
                    SELECT 1
                    FROM users
                    WHERE user_id = $1 AND enabled = true AND deleted_at IS NULL
                    """,
                    selected_user,
                )
                if not user_exists:
                    raise PermissionError("user is disabled or not found")
                device_exists = await conn.fetchval(
                    """
                    SELECT 1
                    FROM devices
                    WHERE device_id = $1
                      AND enabled = true
                      AND deleted_at IS NULL
                      AND status <> 'disabled'
                    """,
                    selected_device,
                )
                if not device_exists:
                    raise PermissionError("device is disabled or not found")

                existing = await conn.fetchrow(
                    """
                    SELECT binding_id, user_id
                    FROM device_bindings
                    WHERE device_id = $1 AND status = 'active'
                    FOR UPDATE
                    """,
                    selected_device,
                )
                if existing is not None:
                    existing_user = str(existing["user_id"])
                    if existing_user != selected_user:
                        raise PermissionError("device is already bound")
                    return {
                        "binding_id": str(existing["binding_id"]),
                        "user_id": selected_user,
                        "device_id": selected_device,
                        "already_bound": True,
                    }

                is_first_activation = False
                device_row = await conn.fetchrow("SELECT status FROM devices WHERE device_id = $1", selected_device)
                if device_row and device_row["status"] == "provisioned":
                    is_first_activation = True

                binding_id = uuid.uuid4().hex
                await conn.execute(
                    """
                    INSERT INTO device_bindings (binding_id, user_id, device_id, status)
                    VALUES ($1, $2, $3, 'active')
                    """,
                    binding_id,
                    selected_user,
                    selected_device,
                )
                await conn.execute(
                    """
                    UPDATE devices
                    SET status = 'bound', updated_at = now()
                    WHERE device_id = $1
                    """,
                    selected_device,
                )
                if is_first_activation:
                    await self.parent._apply_first_activation_gift(conn, selected_device)

                await self._record_binding_event(
                    conn,
                    event_type="device_bound_by_admin",
                    user_id=selected_user,
                    device_id=selected_device,
                    metadata={},
                )
        await self.parent.audit(
            "admin_bind_device",
            "device_binding",
            binding_id,
            {"user_id": selected_user, "device_id": selected_device},
        )
        self._clear_auth_cache(selected_device)
        return {
            "binding_id": binding_id,
            "user_id": selected_user,
            "device_id": selected_device,
            "already_bound": False,
        }

    async def admin_unbind_device(self, *, binding_id: str) -> dict[str, Any]:
        selected_binding = validate_user_id(binding_id)
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT user_id, device_id
                FROM device_bindings
                WHERE binding_id = $1 AND status = 'active'
                """,
                selected_binding,
            )
            if row is None:
                return {"ok": False}
        result = await self._unbind_active_device(
            str(row["user_id"]),
            str(row["device_id"]),
            event_type="device_unbound_by_admin",
        )
        await self.parent.audit(
            "admin_unbind_device",
            "device_binding",
            selected_binding,
            {"user_id": str(row["user_id"]), "device_id": str(row["device_id"])},
        )
        return result

    async def get_device(self, device_id: str | None) -> DeviceConfig:
        selected_id = validate_user_id(device_id or "demo-device-001")
        row = await self.pool.fetchrow(
            """
            SELECT device_id, stt_config, tts_config, llm_config, metadata
            FROM devices
            WHERE device_id = $1 AND enabled = true AND deleted_at IS NULL
            """,
            selected_id,
        )
        if row is None:
            raise PermissionError("device is disabled or not found")
        return DeviceConfig(
            device_id=str(row["device_id"]),
            llm=LLMDeviceConfig(**_json_obj(row["llm_config"])),
            stt=ProviderConfig(**_json_obj(row["stt_config"])),
            tts=ProviderConfig(**_json_obj(row["tts_config"])),
            metadata=_json_obj(row["metadata"]),
        )

    async def touch_device_status(
        self,
        *,
        device_id: str,
        online: bool,
        session_id: str = "",
        error: str = "",
    ) -> None:
        await self.pool.execute(
            """
            INSERT INTO device_status (
                device_id, online, last_seen, current_session_id, last_error, updated_at
            )
            VALUES ($1, $2, now(), $3, $4, now())
            ON CONFLICT (device_id) DO UPDATE SET
                online = excluded.online,
                last_seen = excluded.last_seen,
                current_session_id = excluded.current_session_id,
                last_error = excluded.last_error,
                updated_at = excluded.updated_at
            """,
            device_id,
            online,
            session_id,
            error,
        )

    async def reveal_device_secret(self, device_id: str) -> dict[str, Any]:
        selected_id = _validate_device_code(device_id)
        row = await self.pool.fetchrow(
            """
            SELECT device_id, auth_mode, device_secret_encrypted
            FROM devices
            WHERE device_id = $1 AND deleted_at IS NULL
            """,
            selected_id,
        )
        if row is None:
            raise PermissionError("device is disabled or not found")
        secret, hint = resolve_stored_device_secret(
            auth_mode=str(row["auth_mode"] or ""),
            device_secret_encrypted=str(row["device_secret_encrypted"] or "") or None,
        )
        if not secret:
            raise PermissionError(_secret_unavailable_message(hint))
        await self.parent.audit("reveal_device_secret", "device", selected_id, {"hint": hint})
        return {
            "device_id": selected_id,
            "device_secret": secret,
            "hint": hint,
        }

    async def list_devices(self, *, limit: int = 50, cursor: str = "", q: str = "") -> dict[str, Any]:
        search = _search_pattern(q)
        rows = await self.pool.fetch(
            """
            SELECT d.device_id, d.auth_mode, d.device_secret_hash,
                   d.device_secret_encrypted, d.status AS lifecycle_status,
                   d.stt_config, d.tts_config, d.llm_config, d.enabled, d.note, d.metadata,
                   c.claim_code, c.status AS claim_status,
                   b.user_id AS bound_user_id,
                   b.binding_id AS active_binding_id,
                   s.online, s.last_seen, s.current_session_id, s.last_error
            FROM devices d
            LEFT JOIN device_status s ON s.device_id = d.device_id
            LEFT JOIN device_bindings b
                ON b.device_id = d.device_id AND b.status = 'active'
            LEFT JOIN LATERAL (
                SELECT claim_code, status
                FROM device_claim_codes
                WHERE device_id = d.device_id
                ORDER BY created_at DESC
                LIMIT 1
            ) c ON true
            WHERE d.deleted_at IS NULL
              AND ($1 = '' OR d.device_id > $1)
              AND (
                $3 = ''
                OR d.device_id ILIKE $3
                OR d.note ILIKE $3
                OR d.status ILIKE $3
                OR c.claim_code ILIKE $3
                OR c.status ILIKE $3
              )
            ORDER BY d.device_id ASC
            LIMIT $2
            """,
            cursor,
            max(1, min(limit, 100)),
            search,
        )
        items = [_device_row(row) for row in rows]
        return {
            "items": items,
            "next_cursor": items[-1]["device_id"] if len(items) == limit else "",
            "device_secret_encryption_configured": device_secret_encryption_configured(),
        }

    async def update_device_label(self, device_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        selected_id = _validate_device_code(device_id)
        claim_code = str(payload.get("claim_code") or "").strip()
        if claim_code:
            _validate_claim_code(claim_code)
        note = str(payload.get("note") or "")
        enabled = bool(payload.get("enabled", True))
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                result = await conn.execute(
                    """
                    UPDATE devices
                    SET note = $2, enabled = $3, updated_at = now()
                    WHERE device_id = $1 AND deleted_at IS NULL
                    """,
                    selected_id,
                    note,
                    enabled,
                )
                if not result.endswith("1"):
                    raise PermissionError("device is disabled or not found")
                if claim_code:
                    current_claim = await conn.fetchval(
                        """
                        SELECT claim_code
                        FROM device_claim_codes
                        WHERE device_id = $1
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        selected_id,
                    )
                    if str(current_claim or "") != claim_code:
                        await conn.execute(
                            """
                            UPDATE device_claim_codes
                            SET status = 'revoked'
                            WHERE device_id = $1 AND status = 'active'
                            """,
                            selected_id,
                        )
                        await conn.execute(
                            """
                            INSERT INTO device_claim_codes (
                                claim_code_id, device_id, claim_code, claim_code_hash, status
                            )
                            VALUES ($1, $2, $3, $4, 'active')
                            """,
                            uuid.uuid4().hex,
                            selected_id,
                            claim_code,
                            _hash_secret(claim_code),
                        )
                await self.parent.audit(
                    "update_device_label",
                    "device",
                    selected_id,
                    {"claim_code": claim_code, "note": note, "enabled": enabled},
                )
        return {"device_id": selected_id}

    async def reset_claim_code(self, device_id: str) -> dict[str, Any]:
        selected_id = _validate_device_code(device_id)
        result = await self.pool.execute(
            """
            UPDATE device_claim_codes
            SET status = 'active', claimed_at = NULL
            WHERE claim_code_id = (
                SELECT claim_code_id
                FROM device_claim_codes
                WHERE device_id = $1 AND status IN ('claimed', 'revoked')
                ORDER BY created_at DESC
                LIMIT 1
            )
            """,
            selected_id,
        )
        if not result.endswith("1"):
            raise PermissionError("claim_code is not found")
        await self.parent.audit("reset_claim_code", "device", selected_id, {})
        return {"device_id": selected_id, "claim_status": "active"}

    async def rotate_device_secret(self, device_id: str) -> dict[str, Any]:
        require_device_secret_encryption()
        selected_id = _validate_device_code(device_id)
        device_secret = secrets.token_urlsafe(32)
        result = await self.pool.execute(
            """
            UPDATE devices
            SET auth_mode = 'per_device_secret',
                device_secret_hash = $2,
                device_secret_encrypted = $3,
                updated_at = now()
            WHERE device_id = $1 AND deleted_at IS NULL
            """,
            selected_id,
            _hash_secret(device_secret),
            encrypt_device_secret(device_secret),
        )
        if not result.endswith("1"):
            raise PermissionError("device is disabled or not found")
        await self.parent.audit(
            "rotate_device_secret",
            "device",
            selected_id,
            {"auth_mode": "per_device_secret", "device_secret": "***"},
        )
        return {
            "device_code": selected_id,
            "device_secret": device_secret,
            "auth_mode": "per_device_secret",
        }

    async def upsert_device(self, payload: dict[str, Any]) -> dict[str, Any]:
        device_id = validate_user_id(str(payload.get("device_id") or ""))
        await self.pool.execute(
            """
            INSERT INTO devices (
                device_id, stt_config, tts_config, llm_config, enabled, note, metadata, updated_at
            )
            VALUES ($1, $2::jsonb, $3::jsonb, $4::jsonb, $5, $6, $7::jsonb, now())
            ON CONFLICT (device_id) DO UPDATE SET
                stt_config = excluded.stt_config,
                tts_config = excluded.tts_config,
                llm_config = excluded.llm_config,
                enabled = excluded.enabled,
                note = excluded.note,
                metadata = excluded.metadata,
                updated_at = now(),
                deleted_at = NULL
            """,
            device_id,
            json.dumps(payload.get("stt_config") or {}, ensure_ascii=False),
            json.dumps(payload.get("tts_config") or {}, ensure_ascii=False),
            json.dumps(payload.get("llm_config") or {}, ensure_ascii=False),
            bool(payload.get("enabled", True)),
            str(payload.get("note") or ""),
            json.dumps(payload.get("metadata") or {}, ensure_ascii=False),
        )
        await self.pool.execute(
            "INSERT INTO device_status (device_id) VALUES ($1) ON CONFLICT (device_id) DO NOTHING",
            device_id,
        )
        await self.parent.audit("upsert_device", "device", device_id, _mask_secrets(payload))
        self._clear_auth_cache(device_id)
        return {"device_id": device_id}

    async def soft_delete_device(self, device_id: str) -> None:
        selected_id = validate_user_id(device_id)
        await self.pool.execute(
            "UPDATE devices SET deleted_at = now(), enabled = false, updated_at = now() WHERE device_id = $1",
            selected_id,
        )
        await self.parent.audit("soft_delete_device", "device", selected_id, {})
        self._clear_auth_cache(selected_id)

    async def _unbind_active_device(
        self,
        user_id: str,
        device_id: str,
        *,
        event_type: str,
    ) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                result = await conn.execute(
                    """
                    UPDATE device_bindings
                    SET status = 'unbound', unbound_at = now()
                    WHERE user_id = $1 AND device_id = $2 AND status = 'active'
                    """,
                    user_id,
                    device_id,
                )
                await conn.execute(
                    """
                    UPDATE devices
                    SET status = 'provisioned', updated_at = now()
                    WHERE device_id = $1
                      AND NOT EXISTS (
                        SELECT 1 FROM device_bindings
                        WHERE device_id = $1 AND status = 'active'
                      )
                    """,
                    device_id,
                )
                if result.endswith("1"):
                    await self._restore_latest_claim_code(conn, device_id)
                await self._record_binding_event(
                    conn,
                    event_type=event_type,
                    user_id=user_id,
                    device_id=device_id,
                    metadata={},
                )
        self._clear_auth_cache(device_id)
        return {"ok": result.endswith("1"), "user_id": user_id, "device_code": device_id}

    async def _restore_latest_claim_code(self, conn, device_id: str) -> None:
        await conn.execute(
            """
            UPDATE device_claim_codes
            SET status = 'active', claimed_at = NULL
            WHERE claim_code_id = (
                SELECT claim_code_id
                FROM device_claim_codes
                WHERE device_id = $1 AND status = 'claimed'
                ORDER BY created_at DESC
                LIMIT 1
            )
            """,
            device_id,
        )

    async def _record_auth_failure(self, device_id: str) -> None:
        async with self.pool.acquire() as conn:
            await self._record_binding_event(
                conn,
                event_type="device_auth_failed",
                device_id=device_id,
                metadata={},
            )

    async def _record_binding_event(
        self,
        conn,
        *,
        event_type: str,
        user_id: str | None = None,
        device_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO device_binding_events (
                event_id, user_id, device_id, event_type, metadata
            )
            VALUES ($1, $2, $3, $4, $5::jsonb)
            """,
            uuid.uuid4().hex,
            user_id,
            device_id,
            event_type,
            json.dumps(metadata or {}, ensure_ascii=False),
        )

    async def list_voice_demo_targets(self) -> dict[str, Any]:
        rows = await self.pool.fetch(
            """
            SELECT d.device_id, d.auth_mode, d.device_secret_encrypted,
                   b.user_id, s.online, u.llm_config, u.agent_id,
                   a.display_name AS agent_display_name, a.voice_type AS agent_voice_type
            FROM device_bindings b
            JOIN devices d ON d.device_id = b.device_id
            JOIN users u ON u.user_id = b.user_id
            LEFT JOIN agents a ON a.agent_id = u.agent_id AND a.deleted_at IS NULL
            LEFT JOIN device_status s ON s.device_id = d.device_id
            WHERE b.status = 'active'
              AND d.enabled = true
              AND d.deleted_at IS NULL
              AND d.status <> 'disabled'
            ORDER BY b.user_id ASC, d.device_id ASC
            """
        )
        items: list[dict[str, Any]] = []
        for row in rows:
            secret, hint = resolve_stored_device_secret(
                auth_mode=str(row["auth_mode"] or ""),
                device_secret_encrypted=str(row["device_secret_encrypted"] or "") or None,
            )
            if not secret:
                continue
            llm = _json_obj(row["llm_config"])
            agent_id = str(row["agent_id"] or DEFAULT_AGENT_ID)
            voice_type = str(row["agent_voice_type"] or "")
            items.append(
                {
                    "user_id": str(row["user_id"]),
                    "device_id": str(row["device_id"]),
                    "device_code": str(row["device_id"]),
                    "device_secret": secret,
                    "online": bool(row["online"] or False),
                    "secret_hint": hint,
                    "llm_model": str(llm.get("model") or ""),
                    "llm_base_url": str(llm.get("base_url") or ""),
                    "llm_api_key_configured": bool(llm.get("api_key")),
                    "agent_id": agent_id,
                    "agent_display_name": str(row["agent_display_name"] or agent_id),
                    "tts_voice_type": AgentRecord(
                        agent_id=agent_id,
                        voice_type=voice_type,
                    ).to_public_dict()["voice_type"],
                }
            )
        return {"items": items}

    async def apply_default_stt_to_all_devices(self) -> dict[str, Any]:
        """Set tencent-realtime STT on all non-deleted devices (idempotent)."""
        stt_config = json.dumps(default_tencent_stt_config(), ensure_ascii=False)
        result = await self.pool.execute(
            """
            UPDATE devices
            SET stt_config = $1::jsonb, updated_at = now()
            WHERE deleted_at IS NULL
            """,
            stt_config,
        )
        updated_count = int(result.split()[-1]) if result else 0
        await self.parent.audit(
            "apply_default_stt",
            "device",
            "*",
            {"stt_type": "tencent-realtime", "updated_count": updated_count},
        )
        return {"updated_count": updated_count, "stt_type": "tencent-realtime"}

    async def apply_default_tts_to_all_devices(self) -> dict[str, Any]:
        """Set volcengine-clone TTS on all non-deleted devices (idempotent)."""
        tts_config = json.dumps(default_device_tts_config(), ensure_ascii=False)
        result = await self.pool.execute(
            """
            UPDATE devices
            SET tts_config = $1::jsonb, updated_at = now()
            WHERE deleted_at IS NULL
            """,
            tts_config,
        )
        updated_count = int(result.split()[-1]) if result else 0
        await self.parent.audit(
            "apply_default_tts",
            "device",
            "*",
            {"tts_type": "volcengine-clone", "updated_count": updated_count},
        )
        return {"updated_count": updated_count, "tts_type": "volcengine-clone"}

