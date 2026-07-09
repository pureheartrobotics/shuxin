from __future__ import annotations

import json
import secrets
import uuid
import logging
import os
import re
import yaml
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("shuxin.voice.postgres")

from shuxin.voice.persistence.base_repo import (
    BaseRepository,
    _dt,
    _dt_iso,
    _json_obj,
    _mask_secrets,
    _openid_from_wx_code,
    _hash_secret,
)
from shuxin.voice.persistence.users import (
    validate_user_id,
    DEFAULT_USER_ID,
    UserSettings,
    DEFAULT_AUDIO_QUOTA_MB,
)
from shuxin.voice.persistence.agents import (
    DEFAULT_AGENT_ID,
    AgentRecord,
    invalidate_agent_cache,
)
from shuxin.voice.integrations.dmx_client import (
    dmx_admin_configured,
    create_user_token,
    DEFAULT_QUOTA_YUAN,
    merge_platform_llm_defaults,
)
from shuxin.voice.config.payment_config import DISPLAY_BALANCE_METADATA_KEY
from shuxin.voice.config.config import (
    _merge_dict,
)

def _load_users(config_path: str | None) -> list[dict[str, Any]]:
    path = Path(config_path or os.environ.get("SHUXIN_USERS_CONFIG", "data/users.yaml"))
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    users_dict = data.get("users", {})
    defaults = data.get("defaults", {})
    results = []
    for user_id, user_data in users_dict.items():
        results.append({
            "user_id": user_id,
            "token": str(user_data.get("token", "")),
            "audio_quota_mb": int(user_data.get("audio_quota_mb", defaults.get("audio_quota_mb", 512))),
            "llm_config": dict(user_data.get("llm_config") or defaults.get("llm_config") or {}),
        })
    return results

def _load_devices(config_path: str | None, default_device_id: str) -> list[dict[str, Any]]:
    path = Path(config_path or os.environ.get("VOICE_DEVICE_CONFIG", "data/devices.yaml"))
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    devices_dict = data.get("devices", {})
    defaults = data.get("defaults", {})
    results = []
    for device_id, device_data in devices_dict.items():
        results.append({
            "device_id": device_id,
            "stt": _merge_dict(defaults.get("stt", {}), device_data.get("stt", {})),
            "tts": _merge_dict(defaults.get("tts", {}), device_data.get("tts", {})),
            "llm": _merge_dict(defaults.get("llm", {}), device_data.get("llm", {})),
        })
    return results


def _resolve_openid_from_wx_code():
    from unittest.mock import Mock
    from shuxin.voice.persistence import postgres_repository
    p_func = getattr(postgres_repository, "_openid_from_wx_code", None)
    if p_func and isinstance(p_func, Mock):
        return p_func
    global _openid_from_wx_code
    if isinstance(_openid_from_wx_code, Mock):
        return _openid_from_wx_code
    return p_func or _openid_from_wx_code

def _resolve_dmx_admin_configured():
    from unittest.mock import Mock
    from shuxin.voice.persistence import postgres_repository
    p_func = getattr(postgres_repository, "dmx_admin_configured", None)
    if p_func and isinstance(p_func, Mock):
        return p_func
    global dmx_admin_configured
    if isinstance(dmx_admin_configured, Mock):
        return dmx_admin_configured
    return p_func or dmx_admin_configured

def _resolve_create_user_token():
    from unittest.mock import Mock
    from shuxin.voice.persistence import postgres_repository
    p_func = getattr(postgres_repository, "create_user_token", None)
    if p_func and isinstance(p_func, Mock):
        return p_func
    global create_user_token
    if isinstance(create_user_token, Mock):
        return create_user_token
    return p_func or create_user_token

def _resolve_merge_platform_llm_defaults():
    from unittest.mock import Mock
    from shuxin.voice.persistence import postgres_repository
    p_func = getattr(postgres_repository, "merge_platform_llm_defaults", None)
    if p_func and isinstance(p_func, Mock):
        return p_func
    global merge_platform_llm_defaults
    if isinstance(merge_platform_llm_defaults, Mock):
        return merge_platform_llm_defaults
    return p_func or merge_platform_llm_defaults


class UserRepository(BaseRepository):
    """User and Agent Persistence Repository."""

    async def create_wechat_session(self, *, wx_code: str) -> dict[str, Any]:
        """小程序登录: wx.login code -> openid -> 自定义 session_token。"""
        user_id = validate_user_id(await _resolve_openid_from_wx_code()(wx_code))
        session_token = secrets.token_urlsafe(32)
        async with self.pool.acquire() as conn:
            user_row = await conn.fetchrow(
                "SELECT enabled, deleted_at FROM users WHERE user_id = $1",
                user_id,
            )
            if user_row:
                if not user_row["enabled"] or user_row["deleted_at"] is not None:
                    raise PermissionError("User account is disabled or deleted")

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
                        session_token, user_id, client_id, device_id, expires_at
                    )
                    VALUES ($2, $1, 'miniapp', 'miniapp', now() + interval '30 days')
                    RETURNING expires_at
                )
                SELECT expires_at FROM insert_session
                """,
                user_id,
                session_token,
            )
        await self.audit("create_wechat_session", "session", session_token, {"user_id": user_id})
        return {
            "session_token": session_token,
            "user_id": user_id,
            "expires_at": _dt(expires_at),
        }

    async def ensure_user_dmx_llm(self, user_id: str) -> None:
        """Provision a per-user DMX API key on first login; fill platform LLM defaults."""
        selected_id = validate_user_id(user_id)
        if not _resolve_dmx_admin_configured()():
            logger.info("DMX skip %s: admin credentials not configured", selected_id)
            return
        row = await self.pool.fetchrow(
            "SELECT llm_config, metadata FROM users WHERE user_id = $1 AND deleted_at IS NULL",
            selected_id,
        )
        if row is None:
            logger.info("DMX skip %s: user row not found", selected_id)
            return
        llm_config = _json_obj(row["llm_config"])
        metadata = _json_obj(row["metadata"])
        import copy
        orig_llm_config = copy.deepcopy(llm_config)
        orig_metadata = copy.deepcopy(metadata)

        api_key = str(llm_config.get("api_key") or "").strip()
        newly_provisioned = False
        if not api_key:
            try:
                api_key = await _resolve_create_user_token()(name=selected_id, quota_yuan=DEFAULT_QUOTA_YUAN, unlimited_quota=True)
                newly_provisioned = True
                logger.info("DMX provisioned token for %s", selected_id)
            except Exception as exc:
                logger.warning("DMX token provisioning failed for %s: %s", selected_id, exc)
                return
            llm_config["api_key"] = api_key
        else:
            logger.info("DMX skipped provision for %s: existing api_key", selected_id)
        if newly_provisioned:
            metadata[DISPLAY_BALANCE_METADATA_KEY] = round(
                float(metadata.get(DISPLAY_BALANCE_METADATA_KEY) or 0) + DEFAULT_QUOTA_YUAN,
                4,
            )
        llm_config = _resolve_merge_platform_llm_defaults()(llm_config)
        
        if newly_provisioned or llm_config != orig_llm_config or metadata != orig_metadata:
            await self.pool.execute(
                """
                UPDATE users
                SET llm_config = $2::jsonb,
                    metadata = $3::jsonb,
                    updated_at = now()
                WHERE user_id = $1 AND deleted_at IS NULL
                """,
                selected_id,
                json.dumps(llm_config, ensure_ascii=False),
                json.dumps(metadata, ensure_ascii=False),
            )
            logger.info("DMX saved llm_config for %s", selected_id)
        else:
            logger.info("DMX config unchanged for %s, skipping UPDATE", selected_id)

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

        await self.ensure_default_agents()

    async def authenticate_user(self, user_id: str | None, token: str | None) -> UserSettings:
        selected_id = validate_user_id(user_id or DEFAULT_USER_ID)
        row = await self.pool.fetchrow(
            """
            SELECT user_id, token, audio_quota_mb, llm_config, agent_id
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
            agent_id=str(row["agent_id"] or ""),
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

    async def ensure_default_agents(self) -> None:
        """Seed default shuxin agent and backfill user.agent_id after migrations."""
        voice_type = os.environ.get("VOLCENGINE_TTS_VOICE_TYPE", "")
        await self.pool.execute(
            """
            INSERT INTO agents (
                agent_id, display_name, voice_type, cluster, speed_ratio, encoding,
                uid, soul_path, metadata
            )
            VALUES (
                'shuxin', '初心', $1, 'volcano_icl', 1.0, 'mp3', 'shuxin',
                'SOUL.md', '{}'::jsonb
            )
            ON CONFLICT (agent_id) DO NOTHING
            """,
            voice_type,
        )

    async def list_agents(
        self,
        *,
        limit: int = 50,
        cursor: str = "",
        q: str = "",
    ) -> dict[str, Any]:
        params: list[Any] = [limit]
        conds = ["deleted_at IS NULL"]
        if q:
            conds.append("display_name ILIKE $2")
            params.append(f"%{q}%")
        if cursor:
            idx = len(params) + 1
            conds.append(f"agent_id > ${idx}")
            params.append(cursor)

        where = " AND ".join(conds)
        rows = await self.pool.fetch(
            f"""
            SELECT agent_id, display_name, voice_type, cluster, speed_ratio, encoding,
                   uid, soul_path, enabled, created_at, updated_at, metadata, initial_state
            FROM agents
            WHERE {where}
            ORDER BY agent_id ASC
            LIMIT $1
            """,
            *params,
        )
        items = [AgentRecord.from_row(row).to_admin_dict() for row in rows]
        next_cursor = items[-1]["agent_id"] if items else ""
        return {"items": items, "next_cursor": next_cursor}

    async def get_agent(self, agent_id: str) -> AgentRecord:
        selected = validate_user_id(agent_id)
        row = await self.pool.fetchrow(
            """
            SELECT agent_id, display_name, voice_type, cluster, speed_ratio, encoding,
                   uid, soul_path, enabled, created_at, updated_at, metadata, initial_state
            FROM agents
            WHERE agent_id = $1 AND deleted_at IS NULL
            """,
            selected,
        )
        if row is None:
            raise KeyError(f"agent not found: {selected}")
        return AgentRecord.from_row(row)

    async def get_user_agent_id(self, user_id: str) -> str:
        selected = validate_user_id(user_id)
        agent_id = await self.pool.fetchval(
            "SELECT agent_id FROM users WHERE user_id = $1 AND deleted_at IS NULL",
            selected,
        )
        return str(agent_id or DEFAULT_AGENT_ID)

    async def create_agent(self, payload: dict[str, Any]) -> dict[str, Any]:
        agent_id = validate_user_id(payload.get("agent_id") or "")
        display_name = str(payload.get("display_name") or "")
        voice_type = str(payload.get("voice_type") or "")
        cluster = str(payload.get("cluster") or "volcano_icl")
        speed_ratio = float(payload.get("speed_ratio") or 1.0)
        encoding = str(payload.get("encoding") or "mp3")
        uid = str(payload.get("uid") or agent_id)
        soul_path = str(payload.get("soul_path") or "SOUL.md")
        enabled = bool(payload.get("enabled", True))
        meta = payload.get("metadata") or {}

        await self.pool.execute(
            """
            INSERT INTO agents (
                agent_id, display_name, voice_type, cluster, speed_ratio, encoding,
                uid, soul_path, enabled, metadata, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, now())
            """,
            agent_id,
            display_name,
            voice_type,
            cluster,
            speed_ratio,
            encoding,
            uid,
            soul_path,
            enabled,
            json.dumps(meta, ensure_ascii=False),
        )
        await self.audit("create_agent", "agent", agent_id, _mask_secrets(payload))
        record = await self.get_agent(agent_id)
        return record.to_admin_dict()

    async def update_agent(self, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        selected = validate_user_id(agent_id)
        existing = await self.pool.fetchrow(
            "SELECT * FROM agents WHERE agent_id = $1 AND deleted_at IS NULL",
            selected,
        )
        if existing is None:
            raise KeyError(f"agent not found: {selected}")
        fields = []
        values = []
        index = 1
        mapping = {
            "display_name": str,
            "voice_type": str,
            "cluster": str,
            "encoding": str,
            "uid": str,
            "soul_path": str,
        }
        for key, caster in mapping.items():
            if key not in payload:
                continue
            fields.append(f"{key} = ${index}")
            values.append(caster(payload.get(key) or ""))
            index += 1
        if "speed_ratio" in payload:
            fields.append(f"speed_ratio = ${index}")
            values.append(float(payload["speed_ratio"]))
            index += 1
        if "enabled" in payload:
            fields.append(f"enabled = ${index}")
            values.append(bool(payload["enabled"]))
            index += 1
        if "initial_state" in payload:
            fields.append(f"initial_state = ${index}::jsonb")
            values.append(json.dumps(payload.get("initial_state") or {}, ensure_ascii=False))
            index += 1
        if "metadata" in payload:
            fields.append(f"metadata = ${index}::jsonb")
            values.append(json.dumps(payload.get("metadata") or {}, ensure_ascii=False))
            index += 1
        if not fields:
            record = AgentRecord.from_row(existing)
            return record.to_admin_dict()
        fields.append("updated_at = now()")
        values.append(selected)
        await self.pool.execute(
            f"UPDATE agents SET {', '.join(fields)} WHERE agent_id = ${index}",
            *values,
        )
        invalidate_agent_cache(selected)
        await self.audit("update_agent", "agent", selected, _mask_secrets(payload))
        record = await self.get_agent(selected)
        return record.to_admin_dict()

    async def soft_delete_agent(self, agent_id: str) -> None:
        selected = validate_user_id(agent_id)
        if selected == DEFAULT_AGENT_ID:
            raise ValueError("default agent shuxin cannot be deleted")
        await self.pool.execute(
            """
            UPDATE agents
            SET deleted_at = now(), enabled = false, updated_at = now()
            WHERE agent_id = $1
            """,
            selected,
        )
        invalidate_agent_cache(selected)
        await self.audit("soft_delete_agent", "agent", selected, {})

    async def patch_user(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        selected = validate_user_id(user_id)
        existing = await self.pool.fetchrow(
            "SELECT * FROM users WHERE user_id = $1 AND deleted_at IS NULL",
            selected,
        )
        if existing is None:
            raise KeyError("user not found")
        fields = []
        values = []
        index = 1
        if "token" in payload:
            fields.append(f"token = ${index}")
            values.append(str(payload["token"] or ""))
            index += 1
        if "audio_quota_mb" in payload:
            fields.append(f"audio_quota_mb = ${index}")
            values.append(int(payload["audio_quota_mb"]))
            index += 1
        if "enabled" in payload:
            fields.append(f"enabled = ${index}")
            values.append(bool(payload["enabled"]))
            index += 1
        if "agent_id" in payload:
            fields.append(f"agent_id = ${index}")
            val = payload.get("agent_id")
            values.append(validate_user_id(val) if val else None)
            index += 1
        if "llm_config" in payload:
            fields.append(f"llm_config = ${index}::jsonb")
            values.append(json.dumps(payload.get("llm_config") or {}, ensure_ascii=False))
            index += 1
        if "metadata" in payload:
            fields.append(f"metadata = ${index}::jsonb")
            values.append(json.dumps(payload.get("metadata") or {}, ensure_ascii=False))
            index += 1

        if not fields:
            row = await self.pool.fetchrow("SELECT * FROM users WHERE user_id = $1", selected)
            return dict(row)

        fields.append("updated_at = now()")
        values.append(selected)
        await self.pool.execute(
            f"UPDATE users SET {', '.join(fields)} WHERE user_id = ${index}",
            *values,
        )
        await self.audit("update_user", "user", selected, _mask_secrets(payload))
        row = await self.pool.fetchrow("SELECT * FROM users WHERE user_id = $1", selected)
        return dict(row)

    async def list_users(
        self,
        *,
        limit: int = 50,
        cursor: str = "",
        q: str = "",
    ) -> dict[str, Any]:
        params: list[Any] = [limit]
        conds = ["deleted_at IS NULL"]
        if q:
            conds.append("user_id ILIKE $2")
            params.append(f"%{q}%")
        if cursor:
            idx = len(params) + 1
            conds.append(f"user_id > ${idx}")
            params.append(cursor)

        where = " AND ".join(conds)
        rows = await self.pool.fetch(
            f"""
            SELECT user_id, token, audio_quota_mb, llm_config, agent_id, enabled, created_at, updated_at, metadata
            FROM users
            WHERE {where}
            ORDER BY user_id ASC
            LIMIT $1
            """,
            *params,
        )
        items = []
        for row in rows:
            items.append(
                {
                    "user_id": row["user_id"],
                    "token": row["token"],
                    "audio_quota_mb": row["audio_quota_mb"],
                    "llm_config": _mask_secrets(_json_obj(row["llm_config"])),
                    "agent_id": row["agent_id"] or "",
                    "enabled": row["enabled"],
                    "created_at": _dt(row["created_at"]),
                    "updated_at": _dt(row["updated_at"]),
                    "metadata": _json_obj(row["metadata"]),
                }
            )
        next_cursor = items[-1]["user_id"] if items else ""
        return {"items": items, "next_cursor": next_cursor}

    async def upsert_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        user_id = validate_user_id(str(payload.get("user_id") or ""))
        existing_row = await self.pool.fetchrow(
            """
            SELECT token, audio_quota_mb, token_quota_total, token_quota_used,
                   quota_note, llm_config, enabled, metadata, agent_id
            FROM users
            WHERE user_id = $1
            """,
            user_id,
        )
        llm_config = dict(payload.get("llm_config") or {})
        if not llm_config.get("api_key"):
            llm_config.pop("api_key", None)
            existing_llm = existing_row["llm_config"] if existing_row else None
            llm_config = _merge_dict(_json_obj(existing_llm), llm_config)
        if not llm_config.get("api_key"):
            llm_config.pop("api_key", None)
        agent_id = payload.get("agent_id")
        if agent_id is not None:
            agent_id = str(agent_id).strip() or None
            if agent_id:
                await self.get_agent(agent_id)
        else:
            agent_id = None
        token_value = payload.get("token")
        if token_value is None and existing_row is not None:
            token_value = str(existing_row["token"] or "")
        audio_quota_mb = payload.get("audio_quota_mb")
        if audio_quota_mb is None:
            audio_quota_mb = int(existing_row["audio_quota_mb"]) if existing_row else DEFAULT_AUDIO_QUOTA_MB
        token_quota_total = payload.get("token_quota_total")
        if token_quota_total is None:
            token_quota_total = int(existing_row["token_quota_total"]) if existing_row else 0
        token_quota_used = payload.get("token_quota_used")
        if token_quota_used is None:
            token_quota_used = int(existing_row["token_quota_used"]) if existing_row else 0
        quota_note = payload.get("quota_note")
        if quota_note is None:
            quota_note = str(existing_row["quota_note"] or "") if existing_row else ""
        enabled = payload.get("enabled")
        if enabled is None:
            enabled = bool(existing_row["enabled"]) if existing_row else True
        metadata = payload.get("metadata")
        if metadata is None:
            metadata = _json_obj(existing_row["metadata"]) if existing_row else {}
        await self.pool.execute(
            """
            INSERT INTO users (
                user_id, token, audio_quota_mb, token_quota_total, token_quota_used,
                quota_note, llm_config, enabled, metadata, agent_id, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9::jsonb, $10, now())
            ON CONFLICT (user_id) DO UPDATE SET
                token = excluded.token,
                audio_quota_mb = excluded.audio_quota_mb,
                token_quota_total = excluded.token_quota_total,
                token_quota_used = excluded.token_quota_used,
                quota_note = excluded.quota_note,
                llm_config = excluded.llm_config,
                enabled = excluded.enabled,
                metadata = excluded.metadata,
                agent_id = COALESCE(excluded.agent_id, users.agent_id),
                updated_at = now(),
                deleted_at = NULL
            """,
            user_id,
            str(token_value or ""),
            int(audio_quota_mb),
            max(0, int(token_quota_total)),
            max(0, int(token_quota_used)),
            str(quota_note or ""),
            json.dumps(llm_config, ensure_ascii=False),
            bool(enabled),
            json.dumps(metadata or {}, ensure_ascii=False),
            agent_id,
        )
        if not str(llm_config.get("api_key") or "").strip():
            await self.ensure_user_dmx_llm(user_id)
        self.parent._clear_auth_cache()
        await self.audit("upsert_user", "user", user_id, _mask_secrets({**payload, "token": "***"}))
        return {"user_id": user_id}

    async def hard_delete_user_for_test(self, user_id: str) -> None:
        selected = validate_user_id(user_id)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM wechat_sessions WHERE user_id = $1", selected)
                await conn.execute("DELETE FROM device_bindings WHERE user_id = $1", selected)
                await conn.execute("DELETE FROM users WHERE user_id = $1", selected)

    async def soft_delete_user(self, user_id: str) -> None:
        selected = validate_user_id(user_id)
        await self.pool.execute(
            "UPDATE users SET deleted_at = now(), enabled = false, updated_at = now() WHERE user_id = $1",
            selected,
        )
        await self.audit("soft_delete_user", "user", selected, {})

    async def audit(
        self,
        action: str,
        target_type: str,
        target_id: str,
        metadata: dict[str, Any],
    ) -> None:
        await self.pool.execute(
            """
            INSERT INTO voice_audit_logs (log_id, action, target_type, target_id, metadata)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            """,
            uuid.uuid4().hex,
            action,
            target_type,
            target_id,
            json.dumps(metadata or {}, ensure_ascii=False),
        )

    async def record_adapter_action(
        self,
        *,
        adapter_id: str,
        action: str,
        success: bool,
        error_msg: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.pool.execute(
            """
            INSERT INTO adapter_action_logs (
                log_id, adapter_id, action, success, error_msg, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            """,
            uuid.uuid4().hex,
            adapter_id,
            action,
            success,
            error_msg,
            json.dumps(metadata or {}, ensure_ascii=False),
        )

    async def get_active_announcements(self) -> list[dict[str, Any]]:
        """获取当前生效的公告列表。"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, title, content, type, start_time, end_time, created_at, updated_at
                FROM announcements
                WHERE is_active = true
                  AND (start_time IS NULL OR start_time <= now())
                  AND (end_time IS NULL OR end_time >= now())
                ORDER BY created_at DESC
                """
            )
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "content": row["content"],
                "type": row["type"],
                "start_time": _dt(row["start_time"]) if row["start_time"] else "",
                "end_time": _dt(row["end_time"]) if row["end_time"] else "",
                "created_at": _dt(row["created_at"]),
                "updated_at": _dt(row["updated_at"]),
            }
            for row in rows
        ]

    async def admin_list_announcements(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """管理员列表查询所有公告。"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, title, content, type, is_active, start_time, end_time, created_at, updated_at
                FROM announcements
                ORDER BY created_at DESC
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "content": row["content"],
                "type": row["type"],
                "is_active": row["is_active"],
                "start_time": _dt(row["start_time"]) if row["start_time"] else "",
                "end_time": _dt(row["end_time"]) if row["end_time"] else "",
                "created_at": _dt(row["created_at"]),
                "updated_at": _dt(row["updated_at"]),
            }
            for row in rows
        ]

    async def admin_upsert_announcement(
        self,
        *,
        announcement_id: int | None = None,
        title: str,
        content: str,
        type: str,
        is_active: bool = True,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> dict[str, Any]:
        """新建或更新公告。"""
        async with self.pool.acquire() as conn:
            if announcement_id is not None:
                await conn.execute(
                    """
                    UPDATE announcements
                    SET title = $2, content = $3, type = $4, is_active = $5,
                        start_time = $6, end_time = $7, updated_at = now()
                    WHERE id = $1
                    """,
                    announcement_id,
                    title,
                    content,
                    type,
                    is_active,
                    start_time,
                    end_time,
                )
                res_id = announcement_id
            else:
                res_id = await conn.fetchval(
                    """
                    INSERT INTO announcements (title, content, type, is_active, start_time, end_time)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING id
                    """,
                    title,
                    content,
                    type,
                    is_active,
                    start_time,
                    end_time,
                )
        return {"id": res_id, "ok": True}

    async def admin_delete_announcement(self, announcement_id: int) -> dict[str, Any]:
        """删除公告。"""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM announcements WHERE id = $1",
                announcement_id,
            )
        return {"ok": result.endswith("1")}

    async def create_feedback(self, *, user_id: str, content: str, contact: str = "") -> dict[str, Any]:
        """创建意见反馈。"""
        selected_user = validate_user_id(user_id)
        async with self.pool.acquire() as conn:
            feedback_id = await conn.fetchval(
                """
                INSERT INTO feedbacks (user_id, content, contact, status)
                VALUES ($1, $2, $3, 'pending')
                RETURNING id
                """,
                selected_user,
                content,
                contact,
            )
        return {"id": feedback_id, "ok": True}

    async def admin_list_feedbacks(
        self,
        *,
        status: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """列出意见反馈。"""
        async with self.pool.acquire() as conn:
            if status:
                rows = await conn.fetch(
                    """
                    SELECT id, user_id, content, contact, status, admin_notes, created_at
                    FROM feedbacks
                    WHERE status = $1
                    ORDER BY created_at DESC
                    LIMIT $2 OFFSET $3
                    """,
                    status,
                    limit,
                    offset,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id, user_id, content, contact, status, admin_notes, created_at
                    FROM feedbacks
                    ORDER BY created_at DESC
                    LIMIT $1 OFFSET $2
                    """,
                    limit,
                    offset,
                )
        return [
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "content": row["content"],
                "contact": row["contact"] or "",
                "status": row["status"],
                "admin_notes": row["admin_notes"] or "",
                "created_at": _dt(row["created_at"]),
            }
            for row in rows
        ]

    async def admin_update_feedback(
        self,
        *,
        feedback_id: int,
        status: str,
        admin_notes: str = "",
    ) -> dict[str, Any]:
        """更新反馈状态和备注。"""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE feedbacks
                SET status = $2, admin_notes = $3
                WHERE id = $1
                """,
                feedback_id,
                status,
                admin_notes,
            )
        return {"ok": result.endswith("1")}
