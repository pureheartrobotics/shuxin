from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import uuid
from pathlib import Path
from typing import Any

import yaml

from shuxin.voice.audio_files import compress_wav_to_mp3, sha256_file
from shuxin.voice.config import (
    DeviceConfig,
    LLMDeviceConfig,
    ProviderConfig,
    _expand_env,
    _merge_dict,
    default_device_tts_config,
    default_tencent_stt_config,
)
from shuxin.voice.users import (
    DEFAULT_AUDIO_QUOTA_MB,
    DEFAULT_USER_ID,
    UserSettings,
    validate_user_id,
)

COMPRESS_TARGET_RATIO = 0.8
DEVICE_CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")


class VoicePostgresRepository:
    """Voice Web 的权威数据访问层。"""

    def __init__(self, pool) -> None:
        self.pool = pool

    async def create_wechat_session(self, *, wx_code: str) -> dict[str, Any]:
        """小程序登录: wx.login code -> openid -> 自定义 session_token。"""
        user_id = validate_user_id(await _openid_from_wx_code(wx_code))
        session_token = secrets.token_urlsafe(32)
        async with self.pool.acquire() as conn:
            expires_at = await conn.fetchval(
                """
                WITH upsert_user AS (
                    INSERT INTO users (user_id, metadata, updated_at)
                    VALUES ($1, $2::jsonb, now())
                    ON CONFLICT (user_id) DO UPDATE SET
                        deleted_at = NULL,
                        enabled = true,
                        updated_at = now()
                    RETURNING user_id
                ), insert_session AS (
                    INSERT INTO wechat_sessions (
                        session_token_hash, user_id, expires_at
                    )
                    VALUES ($3, $1, now() + interval '30 days')
                    RETURNING expires_at
                )
                SELECT expires_at FROM insert_session
                """,
                user_id,
                json.dumps({"identity_provider": "wechat"}, ensure_ascii=False),
                _hash_secret(session_token),
            )
        return {
            "session_token": session_token,
            "expires_at": _dt(expires_at),
            "user_id": user_id,
        }

    async def provision_device(self, device_code: str) -> dict[str, Any]:
        """工厂烧录时登记设备，并生成只给用户扫码认领用的 claim_code。"""
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
                    metadata={"provisioned_by": "factory"},
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
                device_id, auth_mode, device_secret_hash, stt_config, tts_config,
                status, enabled, note, metadata, updated_at
            )
            VALUES (
                $1, 'per_device_secret', $2, $3::jsonb, $4::jsonb,
                'provisioned', true, $5, $6::jsonb, now()
            )
            ON CONFLICT (device_id) DO UPDATE SET
                auth_mode = 'per_device_secret',
                device_secret_hash = excluded.device_secret_hash,
                stt_config = excluded.stt_config,
                tts_config = excluded.tts_config,
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
                user_id = await self._user_id_from_wechat_auth(
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
            return {
                "binding_id": str(existing["binding_id"]),
                "user_id": user_id,
                "device_code": device_id,
                "already_bound": True,
            }

        binding_id = uuid.uuid4().hex
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
        await self._record_binding_event(
            conn,
            event_type=event_type,
            user_id=user_id,
            device_id=device_id,
            metadata={},
        )
        return {
            "binding_id": binding_id,
            "user_id": user_id,
            "device_code": device_id,
            "already_bound": False,
        }

    async def authenticate_device(
        self,
        device_code: str | None,
        device_secret: str | None,
    ) -> UserSettings:
        """设备 hello 鉴权，并解析当前 active binding 对应的用户。"""
        selected_code = _validate_device_code(device_code or "")
        row = await self.pool.fetchrow(
            """
            SELECT d.device_id, d.auth_mode, d.device_secret_hash, b.user_id,
                   u.audio_quota_mb, u.llm_config
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

        if not _verify_device_secret(row, device_secret or ""):
            await self._record_auth_failure(selected_code)
            raise PermissionError("invalid device secret")

        return UserSettings(
            user_id=str(row["user_id"]),
            token="",
            audio_quota_mb=int(row["audio_quota_mb"]),
            llm_config=_json_obj(row["llm_config"]),
        )

    async def unbind_device(self, *, user_id: str, device_code: str) -> dict[str, Any]:
        """用户主动解绑设备；保留用户级记忆和资产。"""
        selected_user = validate_user_id(user_id)
        selected_device = _validate_device_code(device_code)
        return await self._unbind_active_device(selected_user, selected_device, event_type="device_unbound")

    async def list_my_devices(self, *, wx_code: str, session_token: str = "") -> dict[str, Any]:
        """小程序端按 wx_code 解析当前用户并列出已绑定设备。"""
        async with self.pool.acquire() as conn:
            user_id = await self._user_id_from_wechat_auth(
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
            user_id = await self._user_id_from_wechat_auth(
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
                await self._record_binding_event(
                    conn,
                    event_type="device_bound_by_admin",
                    user_id=selected_user,
                    device_id=selected_device,
                    metadata={},
                )
        await self.audit(
            "admin_bind_device",
            "device_binding",
            binding_id,
            {"user_id": selected_user, "device_id": selected_device},
        )
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
        await self.audit(
            "admin_unbind_device",
            "device_binding",
            selected_binding,
            {"user_id": str(row["user_id"]), "device_id": str(row["device_id"])},
        )
        return result

    async def seed_from_yaml(
        self,
        *,
        device_config_path: str | None,
        users_config_path: str | None,
        default_device_id: str,
    ) -> None:
        """首次启动时把开发 YAML 导入 Postgres，后续以 DB 为准。"""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                user_count = await conn.fetchval("SELECT COUNT(*) FROM users")
                if int(user_count or 0) == 0:
                    for user in _load_users(users_config_path):
                        await conn.execute(
                            """
                            INSERT INTO users (
                                user_id, token, audio_quota_mb, llm_config, enabled, metadata
                            )
                            VALUES ($1, $2, $3, $4::jsonb, true, $5::jsonb)
                            ON CONFLICT (user_id) DO NOTHING
                            """,
                            user["user_id"],
                            user["token"],
                            user["audio_quota_mb"],
                            json.dumps(user["llm_config"], ensure_ascii=False),
                            json.dumps({"seeded_from": "yaml"}),
                        )

                device_count = await conn.fetchval("SELECT COUNT(*) FROM devices")
                if int(device_count or 0) == 0:
                    for device in _load_devices(device_config_path, default_device_id):
                        await conn.execute(
                            """
                            INSERT INTO devices (
                                device_id, stt_config, tts_config, llm_config, enabled, note, metadata
                            )
                            VALUES ($1, $2::jsonb, $3::jsonb, $4::jsonb, true, $5, $6::jsonb)
                            ON CONFLICT (device_id) DO NOTHING
                            """,
                            device["device_id"],
                            json.dumps(device["stt"], ensure_ascii=False),
                            json.dumps(device["tts"], ensure_ascii=False),
                            json.dumps(device["llm"], ensure_ascii=False),
                            "seeded development device",
                            json.dumps({"seeded_from": "yaml"}),
                        )
                        await conn.execute(
                            """
                            INSERT INTO device_status (device_id)
                            VALUES ($1)
                            ON CONFLICT (device_id) DO NOTHING
                            """,
                            device["device_id"],
                        )

    async def authenticate_user(self, user_id: str | None, token: str | None) -> UserSettings:
        selected_id = validate_user_id(user_id or DEFAULT_USER_ID)
        row = await self.pool.fetchrow(
            """
            SELECT user_id, token, audio_quota_mb, llm_config
            FROM users
            WHERE user_id = $1 AND enabled = true AND deleted_at IS NULL
            """,
            selected_id,
        )
        if row is None:
            raise PermissionError("user is disabled or not found")
        expected = str(row["token"] or "")
        if expected and token != expected:
            raise PermissionError("invalid user token")
        if not expected and selected_id != DEFAULT_USER_ID:
            raise PermissionError("user token is not configured")
        return UserSettings(
            user_id=str(row["user_id"]),
            token=expected,
            audio_quota_mb=int(row["audio_quota_mb"]),
            llm_config=_json_obj(row["llm_config"]),
        )

    async def get_device(self, device_id: str | None) -> DeviceConfig:
        selected_id = validate_user_id(device_id or "demo-device-001")
        row = await self.pool.fetchrow(
            """
            SELECT device_id, stt_config, tts_config, llm_config
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

    async def ensure_session(
        self,
        *,
        session_id: str,
        user_id: str,
        device_id: str,
        client_id: str,
    ) -> None:
        await self.pool.execute(
            """
            INSERT INTO voice_sessions (session_id, user_id, device_id, client_id)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (session_id) DO NOTHING
            """,
            session_id,
            user_id,
            device_id,
            client_id,
        )

    async def record_turn(
        self,
        *,
        user_settings: UserSettings,
        device_id: str,
        client_id: str,
        session_id: str,
        turn_id: str,
        user_text: str,
        reply_text: str,
        input_audio: Path | None,
        reply_audio: Path | None,
        timings: dict[str, int],
        warning: str = "",
    ) -> None:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO conversation_events (
                        event_id, user_id, device_id, session_id, turn_id, event_type,
                        user_text, reply_text, metadata
                    )
                    VALUES ($1, $2, $3, $4, $5, 'conversation_turn', $6, $7, $8::jsonb)
                    """,
                    uuid.uuid4().hex,
                    user_settings.user_id,
                    device_id,
                    session_id,
                    turn_id,
                    user_text,
                    reply_text,
                    json.dumps({"timings": timings, "warning": warning}, ensure_ascii=False),
                )
                for kind, path, media_type, compressed in [
                    ("input", input_audio, "audio/wav", False),
                    ("reply", reply_audio, "audio/mpeg", True),
                ]:
                    if path and path.exists():
                        await self._insert_attachment(
                            conn,
                            user_id=user_settings.user_id,
                            device_id=device_id,
                            session_id=session_id,
                            turn_id=turn_id,
                            kind=kind,
                            path=path,
                            media_type=media_type,
                            compressed=compressed,
                        )
                await self._upsert_facts_from_text(conn, user_settings.user_id, user_text)
                await self._refresh_shared_memory(conn, user_settings, warning)

    async def status(self, user_settings: UserSettings) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            used = await self._attachment_total_bytes(conn, user_settings.user_id)
            summary = await conn.fetchval(
                "SELECT summary FROM shared_memory WHERE user_id = $1",
                user_settings.user_id,
            )
        return {
            "user_id": user_settings.user_id,
            "audio_quota_bytes": user_settings.audio_quota_bytes,
            "audio_used_bytes": used,
            "over_quota": used > user_settings.audio_quota_bytes,
            "pending_jobs": 0,
            "warnings": [],
            "shared_memory": _json_obj(summary),
        }

    async def export_summary(self, user_settings: UserSettings) -> dict[str, Any]:
        summary = await self.pool.fetchval(
            "SELECT summary FROM shared_memory WHERE user_id = $1",
            user_settings.user_id,
        )
        return _json_obj(summary)

    async def compress_if_needed(self, user_settings: UserSettings) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                used = await self._attachment_total_bytes(conn, user_settings.user_id)
                quota = user_settings.audio_quota_bytes
                if used <= quota:
                    return {"compressed": 0, "used_bytes": used, "over_quota": False}

                target = int(quota * COMPRESS_TARGET_RATIO)
                rows = await conn.fetch(
                    """
                    SELECT attachment_id, path, size_bytes
                    FROM audio_attachments
                    WHERE user_id = $1
                      AND deleted_at IS NULL
                      AND kind = 'input'
                      AND compressed = false
                    ORDER BY created_at ASC, attachment_id ASC
                    """,
                    user_settings.user_id,
                )
                compressed_count = 0
                for row in rows:
                    if used <= target:
                        break
                    path = Path(str(row["path"]))
                    if not path.exists():
                        await conn.execute(
                            "UPDATE audio_attachments SET deleted_at = now() WHERE attachment_id = $1",
                            row["attachment_id"],
                        )
                        continue
                    compressed_path = path.with_suffix(".mp3")
                    compress_wav_to_mp3(path, compressed_path)
                    old_size = int(row["size_bytes"] or path.stat().st_size)
                    path.unlink(missing_ok=True)
                    new_size = compressed_path.stat().st_size
                    await conn.execute(
                        """
                        UPDATE audio_attachments
                        SET path = $1,
                            media_type = 'audio/mpeg',
                            size_bytes = $2,
                            sha256 = $3,
                            compressed = true
                        WHERE attachment_id = $4
                        """,
                        str(compressed_path),
                        new_size,
                        sha256_file(compressed_path),
                        row["attachment_id"],
                    )
                    used = used - old_size + new_size
                    compressed_count += 1
                return {
                    "compressed": compressed_count,
                    "used_bytes": used,
                    "over_quota": used > quota,
                }

    async def list_devices(self, *, limit: int = 50, cursor: str = "", q: str = "") -> dict[str, Any]:
        search = _search_pattern(q)
        rows = await self.pool.fetch(
            """
            SELECT d.device_id, d.auth_mode, d.device_secret_hash, d.stt_config,
                   d.tts_config, d.llm_config, d.enabled, d.note, d.metadata,
                   c.claim_code, c.status AS claim_status,
                   s.online, s.last_seen, s.current_session_id, s.last_error
            FROM devices d
            LEFT JOIN device_status s ON s.device_id = d.device_id
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
        return {"items": items, "next_cursor": items[-1]["device_id"] if len(items) == limit else ""}


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
        await self.audit(
            "apply_default_stt",
            "device",
            "*",
            {"stt_type": "tencent-realtime", "updated_count": updated_count},
        )
        return {"updated_count": updated_count, "stt_type": "tencent-realtime"}

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
                await self.audit(
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
        await self.audit("reset_claim_code", "device", selected_id, {})
        return {"device_id": selected_id, "claim_status": "active"}

    async def rotate_device_secret(self, device_id: str) -> dict[str, Any]:
        selected_id = _validate_device_code(device_id)
        device_secret = secrets.token_urlsafe(32)
        result = await self.pool.execute(
            """
            UPDATE devices
            SET auth_mode = 'per_device_secret',
                device_secret_hash = $2,
                updated_at = now()
            WHERE device_id = $1 AND deleted_at IS NULL
            """,
            selected_id,
            _hash_secret(device_secret),
        )
        if not result.endswith("1"):
            raise PermissionError("device is disabled or not found")
        await self.audit(
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
        await self.audit("upsert_device", "device", device_id, _mask_secrets(payload))
        return {"device_id": device_id}

    async def soft_delete_device(self, device_id: str) -> None:
        selected_id = validate_user_id(device_id)
        await self.pool.execute(
            "UPDATE devices SET deleted_at = now(), enabled = false, updated_at = now() WHERE device_id = $1",
            selected_id,
        )
        await self.audit("soft_delete_device", "device", selected_id, {})

    async def list_users(self, *, limit: int = 50, cursor: str = "", q: str = "") -> dict[str, Any]:
        search = _search_pattern(q)
        rows = await self.pool.fetch(
            """
            SELECT user_id, token <> '' AS token_configured, audio_quota_mb,
                   token_quota_total, token_quota_used, quota_note, llm_config,
                   enabled, metadata, created_at, updated_at
            FROM users
            WHERE deleted_at IS NULL
              AND ($1 = '' OR user_id > $1)
              AND (
                $3 = ''
                OR user_id ILIKE $3
                OR quota_note ILIKE $3
                OR COALESCE(llm_config->>'model', '') ILIKE $3
                OR COALESCE(llm_config->>'base_url', '') ILIKE $3
              )
            ORDER BY user_id ASC
            LIMIT $2
            """,
            cursor,
            max(1, min(limit, 100)),
            search,
        )
        items = [
            {
                "user_id": str(row["user_id"]),
                "token_configured": bool(row["token_configured"]),
                "audio_quota_mb": int(row["audio_quota_mb"]),
                "token_quota_total": int(row["token_quota_total"]),
                "token_quota_used": int(row["token_quota_used"]),
                "quota_note": str(row["quota_note"] or ""),
                "llm_config": _mask_secrets(_json_obj(row["llm_config"])),
                "enabled": bool(row["enabled"]),
                "metadata": _json_obj(row["metadata"]),
                "created_at": _dt(row["created_at"]),
                "updated_at": _dt(row["updated_at"]),
            }
            for row in rows
        ]
        return {"items": items, "next_cursor": items[-1]["user_id"] if len(items) == limit else ""}

    async def upsert_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        user_id = validate_user_id(str(payload.get("user_id") or ""))
        llm_config = dict(payload.get("llm_config") or {})
        if not llm_config.get("api_key"):
            existing_llm = await self.pool.fetchval(
                "SELECT llm_config FROM users WHERE user_id = $1",
                user_id,
            )
            llm_config = _merge_dict(_json_obj(existing_llm), llm_config)
            if not llm_config.get("api_key"):
                llm_config.pop("api_key", None)
        await self.pool.execute(
            """
            INSERT INTO users (
                user_id, token, audio_quota_mb, token_quota_total, token_quota_used,
                quota_note, llm_config, enabled, metadata, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9::jsonb, now())
            ON CONFLICT (user_id) DO UPDATE SET
                token = excluded.token,
                audio_quota_mb = excluded.audio_quota_mb,
                token_quota_total = excluded.token_quota_total,
                token_quota_used = excluded.token_quota_used,
                quota_note = excluded.quota_note,
                llm_config = excluded.llm_config,
                enabled = excluded.enabled,
                metadata = excluded.metadata,
                updated_at = now(),
                deleted_at = NULL
            """,
            user_id,
            str(payload.get("token") or ""),
            int(payload.get("audio_quota_mb") or DEFAULT_AUDIO_QUOTA_MB),
            max(0, int(payload.get("token_quota_total") or 0)),
            max(0, int(payload.get("token_quota_used") or 0)),
            str(payload.get("quota_note") or ""),
            json.dumps(llm_config, ensure_ascii=False),
            bool(payload.get("enabled", True)),
            json.dumps(payload.get("metadata") or {}, ensure_ascii=False),
        )
        await self.audit("upsert_user", "user", user_id, _mask_secrets({**payload, "token": "***"}))
        return {"user_id": user_id}

    async def soft_delete_user(self, user_id: str) -> None:
        selected_id = validate_user_id(user_id)
        await self.pool.execute(
            "UPDATE users SET deleted_at = now(), enabled = false, updated_at = now() WHERE user_id = $1",
            selected_id,
        )
        await self.audit("soft_delete_user", "user", selected_id, {})

    async def audit(self, action: str, target_type: str, target_id: str, metadata: dict[str, Any]) -> None:
        await self.pool.execute(
            """
            INSERT INTO admin_audit_logs (audit_id, action, target_type, target_id, metadata)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            """,
            uuid.uuid4().hex,
            action,
            target_type,
            target_id,
            json.dumps(metadata, ensure_ascii=False),
        )

    async def record_adapter_action(
        self,
        *,
        adapter_name: str,
        action: str,
        request_json: dict[str, Any],
        result_json: dict[str, Any] | list[Any] | None = None,
        error: str = "",
    ) -> None:
        await self.pool.execute(
            """
            INSERT INTO adapter_actions (
                action_id, adapter_name, action, status, request_json, result_json, error
            )
            VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7)
            """,
            uuid.uuid4().hex,
            adapter_name,
            action,
            "error" if error else "ok",
            json.dumps(request_json, ensure_ascii=False),
            json.dumps(result_json or {}, ensure_ascii=False),
            error,
        )

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

    async def _insert_attachment(
        self,
        conn,
        *,
        user_id: str,
        device_id: str,
        session_id: str,
        turn_id: str,
        kind: str,
        path: Path,
        media_type: str,
        compressed: bool,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO audio_attachments (
                attachment_id, user_id, device_id, session_id, turn_id, kind,
                path, media_type, size_bytes, sha256, compressed
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            """,
            uuid.uuid4().hex,
            user_id,
            device_id,
            session_id,
            turn_id,
            kind,
            str(path),
            media_type,
            path.stat().st_size,
            sha256_file(path),
            compressed,
        )

    async def _attachment_total_bytes(self, conn, user_id: str) -> int:
        value = await conn.fetchval(
            """
            SELECT COALESCE(SUM(size_bytes), 0)
            FROM audio_attachments
            WHERE user_id = $1 AND deleted_at IS NULL
            """,
            user_id,
        )
        return int(value or 0)

    async def _refresh_shared_memory(
        self,
        conn,
        user_settings: UserSettings,
        warning: str,
    ) -> None:
        event_count = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM conversation_events
            WHERE user_id = $1 AND deleted_at IS NULL
            """,
            user_settings.user_id,
        )
        used = await self._attachment_total_bytes(conn, user_settings.user_id)
        summary = {
            "user_id": user_settings.user_id,
            "turn_count": int(event_count or 0),
            "audio_quota_bytes": user_settings.audio_quota_bytes,
            "audio_used_bytes": used,
            "over_quota": used > user_settings.audio_quota_bytes,
            "last_warning": warning,
        }
        await conn.execute(
            """
            INSERT INTO shared_memory (user_id, summary, updated_at)
            VALUES ($1, $2::jsonb, now())
            ON CONFLICT (user_id) DO UPDATE SET
                summary = excluded.summary,
                updated_at = now()
            """,
            user_settings.user_id,
            json.dumps(summary, ensure_ascii=False),
        )

    async def _upsert_facts_from_text(self, conn, user_id: str, text: str) -> None:
        for fact_key, fact_value, category in _extract_facts(text):
            existing = await conn.fetchval(
                """
                SELECT fact_id
                FROM user_facts
                WHERE user_id = $1 AND fact_key = $2 AND deleted_at IS NULL
                LIMIT 1
                """,
                user_id,
                fact_key,
            )
            if existing:
                await conn.execute(
                    """
                    UPDATE user_facts
                    SET fact_value = $1, category = $2, confidence = 1.0, updated_at = now()
                    WHERE fact_id = $3
                    """,
                    fact_value,
                    category,
                    existing,
                )
            else:
                await conn.execute(
                    """
                    INSERT INTO user_facts (
                        fact_id, user_id, fact_key, fact_value, category, confidence
                    )
                    VALUES ($1, $2, $3, $4, $5, 1.0)
                    """,
                    uuid.uuid4().hex,
                    user_id,
                    fact_key,
                    fact_value,
                    category,
                )


def _load_users(path: str | None) -> list[dict[str, Any]]:
    data = _load_yaml(path)
    defaults = data.get("defaults", {}) if isinstance(data, dict) else {}
    users = data.get("users", {}) if isinstance(data, dict) else {}
    items: list[dict[str, Any]] = []
    for user_id, raw in users.items():
        raw = raw or {}
        items.append(
            {
                "user_id": validate_user_id(str(user_id)),
                "token": str(raw.get("token", "")),
                "audio_quota_mb": int(
                    raw.get("audio_quota_mb", defaults.get("audio_quota_mb", DEFAULT_AUDIO_QUOTA_MB))
                ),
                "llm_config": _expand_env(raw.get("llm_config") or defaults.get("llm_config") or {}),
            }
        )
    if not any(item["user_id"] == DEFAULT_USER_ID for item in items):
        items.append(
            {
                "user_id": DEFAULT_USER_ID,
                "token": "",
                "audio_quota_mb": int(defaults.get("audio_quota_mb", DEFAULT_AUDIO_QUOTA_MB)),
                "llm_config": _expand_env(defaults.get("llm_config") or {}),
            }
        )
    return items


def _load_devices(path: str | None, default_device_id: str) -> list[dict[str, Any]]:
    data = _expand_env(_load_yaml(path))
    defaults = data.get("defaults", {}) if isinstance(data, dict) else {}
    devices = data.get("devices", {}) if isinstance(data, dict) else {}
    selected: list[dict[str, Any]] = []
    for device_id, raw in devices.items():
        merged = _merge_dict(defaults, raw or {})
        selected.append(
            {
                "device_id": validate_user_id(str(device_id)),
                "llm": merged.get("llm", {}),
                "stt": merged.get("stt", {}),
                "tts": merged.get("tts", {}),
            }
        )
    if not selected:
        selected.append(
            {
                "device_id": validate_user_id(default_device_id),
                "llm": {},
                "stt": {"type": "local"},
                "tts": {"type": "local"},
            }
        )
    return selected


def _load_yaml(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    config_path = Path(path)
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML config must be a mapping: {config_path}")
    return data


def _extract_facts(text: str) -> list[tuple[str, str, str]]:
    updates: list[tuple[str, str, str]] = []
    for pattern, key_prefix, category in [
        (r"我喜欢([^，。,.!！?？]{1,30})", "喜欢", "preference"),
        (r"我不喜欢([^，。,.!！?？]{1,30})", "不喜欢", "preference"),
        (r"我叫([^，。,.!！?？]{1,20})", "名字", "general"),
        (r"以后叫我([^，。,.!！?？]{1,20})", "称呼", "general"),
    ]:
        match = re.search(pattern, text)
        if match:
            value = match.group(1).strip()
            if value:
                updates.append((key_prefix, value, category))
    return updates


def _json_obj(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return json.loads(value) if value else {}
    return dict(value)


def _dt(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")


def _device_row(row) -> dict[str, Any]:
    return {
        "device_id": str(row["device_id"]),
        "device_code": str(row["device_id"]),
        "auth_mode": str(row["auth_mode"] or "shared_secret"),
        "device_secret_configured": bool(row["device_secret_hash"]),
        "claim_code": str(row["claim_code"] or ""),
        "claim_status": str(row["claim_status"] or ""),
        "stt_config": _json_obj(row["stt_config"]),
        "tts_config": _json_obj(row["tts_config"]),
        "llm_config": _mask_secrets(_json_obj(row["llm_config"])),
        "enabled": bool(row["enabled"]),
        "note": str(row["note"] or ""),
        "metadata": _json_obj(row["metadata"]),
        "status": {
            "online": bool(row["online"] or False),
            "last_seen": _dt(row["last_seen"]),
            "current_session_id": str(row["current_session_id"] or ""),
            "last_error": str(row["last_error"] or ""),
        },
    }


def _binding_row(row) -> dict[str, Any]:
    return {
        "binding_id": str(row["binding_id"]),
        "user_id": str(row["user_id"]),
        "device_id": str(row["device_id"]),
        "device_code": str(row["device_id"]),
        "status": str(row["status"]),
        "bound_at": _dt(row["bound_at"]),
        "device": {
            "enabled": bool(row["enabled"]),
            "note": str(row["note"] or ""),
            "metadata": _json_obj(row["metadata"]),
        },
        "online": bool(row["online"] or False),
        "last_seen": _dt(row["last_seen"]),
        "current_session_id": str(row["current_session_id"] or ""),
        "last_error": str(row["last_error"] or ""),
    }


def _mask_secrets(value: dict[str, Any]) -> dict[str, Any]:
    masked: dict[str, Any] = {}
    for key, item in value.items():
        lowered = str(key).lower()
        if any(secret_key in lowered for secret_key in ["key", "token", "password", "secret"]):
            masked[key] = "***" if item else ""
        elif isinstance(item, dict):
            masked[key] = _mask_secrets(item)
        else:
            masked[key] = item
    return masked


def _validate_device_code(device_code: str) -> str:
    selected = str(device_code or "").strip()
    if not DEVICE_CODE_PATTERN.fullmatch(selected):
        raise ValueError(
            "device_code must be 1-96 chars and contain only letters, digits, dot, dash, "
            "underscore or colon"
        )
    return selected


def _validate_claim_code(claim_code: str) -> str:
    selected = str(claim_code or "").strip()
    if not DEVICE_CODE_PATTERN.fullmatch(selected):
        raise ValueError(
            "claim_code must be 1-96 chars and contain only letters, digits, dot, dash, "
            "underscore or colon"
        )
    return selected


def _search_pattern(q: str) -> str:
    selected = str(q or "").strip()
    return f"%{selected}%" if selected else ""


def _validate_code_prefix(value: str) -> str:
    selected = str(value or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{0,15}", selected):
        raise ValueError("prefix must be 1-16 uppercase letters, digits or dash")
    return selected


def _make_device_id(prefix: str, sequence: int) -> str:
    return _validate_device_code(f"{prefix}-{sequence:06d}")


def _make_claim_code(prefix: str, batch: str, sequence: int) -> str:
    return _validate_claim_code(f"{prefix}-{batch}-{sequence:06d}")


def _device_sequence(device_id: str) -> int | None:
    match = re.search(r"(\d+)$", device_id)
    return int(match.group(1)) if match else None


def _hash_secret(value: str) -> str:
    pepper = os.environ.get("SHUXIN_SECRET_PEPPER", "")
    return hashlib.sha256(f"{pepper}:{value}".encode("utf-8")).hexdigest()


def _verify_hash(value: str, expected_hash: str | None) -> bool:
    if not expected_hash:
        return False
    return hmac.compare_digest(_hash_secret(value), str(expected_hash))


def _verify_device_secret(row: Any, device_secret: str) -> bool:
    auth_mode = str(row["auth_mode"] or "shared_secret")
    if auth_mode == "shared_secret":
        expected = os.environ.get("SHUXIN_DEVICE_SHARED_SECRET", "")
        return bool(expected) and hmac.compare_digest(device_secret, expected)
    if auth_mode == "per_device_secret":
        return _verify_hash(device_secret, row["device_secret_hash"])
    return False


async def _openid_from_wx_code(wx_code: str) -> str:
    """把小程序 wx.login code 换成 openid；本地开发可显式启用 mock。"""
    code = str(wx_code or "").strip()
    if not code:
        raise PermissionError("wx_code is required")

    if os.environ.get("SHUXIN_WECHAT_MOCK", "").lower() in {"1", "true", "yes"}:
        return validate_user_id(f"wx_{_hash_secret(code)[:24]}")

    app_id = os.environ.get("SHUXIN_WECHAT_APPID") or os.environ.get("WECHAT_MINIPROGRAM_APPID", "")
    app_secret = os.environ.get("SHUXIN_WECHAT_SECRET") or os.environ.get("WECHAT_MINIPROGRAM_SECRET", "")
    if not app_id or not app_secret:
        raise RuntimeError("SHUXIN_WECHAT_APPID and SHUXIN_WECHAT_SECRET are required")

    import httpx

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            "https://api.weixin.qq.com/sns/jscode2session",
            params={
                "appid": app_id,
                "secret": app_secret,
                "js_code": code,
                "grant_type": "authorization_code",
            },
        )
    response.raise_for_status()
    data = response.json()
    if data.get("errcode"):
        raise PermissionError(f"wechat login failed: {data.get('errmsg', data.get('errcode'))}")
    openid = str(data.get("openid") or "")
    if not openid:
        raise PermissionError("wechat login did not return openid")
    return validate_user_id(openid)
