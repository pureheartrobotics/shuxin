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
from typing import Any

from shuxin.voice.payment_config import (
    DEFAULT_CREDIT_RATIO,
    DISPLAY_BALANCE_METADATA_KEY,
    PAYMENT_CREDIT_RATIO_SETTING_KEY,
    PaymentPlan,
    compute_payment_credits,
    normalize_credit_ratio,
    plan_from_row,
)
from shuxin.voice.time_display import format_beijing_display, format_beijing_iso
from shuxin.voice.dmx_client import (
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

from shuxin.voice.audio_files import compress_wav_to_mp3, purge_attachment_file, sha256_file
from shuxin.voice.device_secret_crypto import (
    device_secret_encryption_configured,
    encrypt_device_secret,
    mask_device_secret,
    require_device_secret_encryption,
    resolve_stored_device_secret,
)
from shuxin.voice.config import (
    DeviceConfig,
    LLMDeviceConfig,
    ProviderConfig,
    _expand_env,
    _merge_dict,
    default_device_tts_config,
    default_tencent_stt_config,
)
from shuxin.voice.memory_summary import (
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
from shuxin.voice.agents import (
    DEFAULT_AGENT_ID,
    AgentRecord,
    cache_agent,
    get_cached_agent,
    invalidate_agent_cache,
)
from shuxin.voice.users import (
    DEFAULT_AUDIO_QUOTA_MB,
    DEFAULT_USER_ID,
    FACTORY_PROBE_USER_ID,
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
        result = {
            "session_token": session_token,
            "expires_at": _dt_iso(expires_at),
            "user_id": user_id,
        }
        await self.ensure_user_dmx_llm(user_id)
        return result

    async def ensure_user_dmx_llm(self, user_id: str) -> None:
        """Provision a per-user DMX API key on first login; fill platform LLM defaults."""
        selected_id = validate_user_id(user_id)
        if not dmx_admin_configured():
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
        api_key = str(llm_config.get("api_key") or "").strip()
        newly_provisioned = False
        if not api_key:
            try:
                api_key = await create_user_token(name=selected_id, quota_yuan=DEFAULT_QUOTA_YUAN)
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
        llm_config = merge_platform_llm_defaults(llm_config)
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

    async def get_credit_ratio(self) -> float:
        row = await self.pool.fetchrow(
            """
            SELECT value
            FROM platform_settings
            WHERE key = $1
            """,
            PAYMENT_CREDIT_RATIO_SETTING_KEY,
        )
        if row is None:
            return DEFAULT_CREDIT_RATIO
        payload = _json_obj(row["value"])
        try:
            return normalize_credit_ratio(float(payload.get("ratio") or DEFAULT_CREDIT_RATIO))
        except ValueError:
            return DEFAULT_CREDIT_RATIO

    async def set_credit_ratio(self, ratio: float) -> dict[str, Any]:
        normalized = normalize_credit_ratio(ratio)
        await self.pool.execute(
            """
            INSERT INTO platform_settings (key, value, updated_at)
            VALUES ($1, $2::jsonb, now())
            ON CONFLICT (key) DO UPDATE SET
                value = excluded.value,
                updated_at = now()
            """,
            PAYMENT_CREDIT_RATIO_SETTING_KEY,
            json.dumps({"ratio": normalized}, ensure_ascii=False),
        )
        return {"credit_ratio": normalized}

    async def get_payment_settings(self) -> dict[str, Any]:
        ratio = await self.get_credit_ratio()
        return {"credit_ratio": ratio}

    async def list_payment_plans(self, *, include_disabled: bool = False) -> list[PaymentPlan]:
        rows = await self.pool.fetch(
            """
            SELECT plan_id, name, description, amount_fen, sort_order, enabled
            FROM payment_plans
            WHERE ($1::boolean OR enabled = true)
            ORDER BY sort_order ASC, plan_id ASC
            """,
            include_disabled,
        )
        if rows:
            return [plan_from_row(row) for row in rows]
        from shuxin.voice.payment_config import load_payment_plans

        return load_payment_plans()

    async def list_miniapp_payment_plans(self) -> list[dict[str, Any]]:
        """获取所有已启用的订阅套餐和充值加油包，格式化后供小程序直接加载展示。"""
        async with self.pool.acquire() as conn:
            sub_rows = await conn.fetch(
                """
                SELECT plan_id, name, amount_fen, duration_minutes, description
                FROM miniapp_subscription_plans
                WHERE enabled = true
                ORDER BY sort_order ASC, plan_id ASC
                """
            )
            fuel_rows = await conn.fetch(
                """
                SELECT package_id, name, amount_fen, duration_minutes, description
                FROM miniapp_fuel_packages
                WHERE enabled = true
                ORDER BY sort_order ASC, package_id ASC
                """
            )
        
        items = []
        for r in sub_rows:
            items.append({
                "id": r["plan_id"],
                "name": r["name"],
                "description": r["description"] or f"{r['duration_minutes']}分钟/月",
                "amount_fen": r["amount_fen"],
                "amount_yuan": round(r["amount_fen"] / 100, 2),
                "type": "subscription",
                "duration_minutes": r["duration_minutes"],
            })
        for r in fuel_rows:
            items.append({
                "id": r["package_id"],
                "name": r["name"],
                "description": r["description"] or f"{r['duration_minutes']}分钟",
                "amount_fen": r["amount_fen"],
                "amount_yuan": round(r["amount_fen"] / 100, 2),
                "type": "fuel_pack",
                "duration_minutes": r["duration_minutes"],
            })
        return items

    async def get_payment_plan(self, plan_id: str) -> PaymentPlan:
        selected = str(plan_id or "").strip()
        row = await self.pool.fetchrow(
            """
            SELECT plan_id, name, description, amount_fen, sort_order, enabled
            FROM payment_plans
            WHERE plan_id = $1
            """,
            selected,
        )
        if row is not None:
            plan = plan_from_row(row)
            if not plan.enabled:
                raise ValueError(f"payment plan disabled: {selected}")
            return plan
        count = await self.pool.fetchval("SELECT COUNT(*) FROM payment_plans")
        if int(count or 0) > 0:
            raise ValueError(f"unknown payment plan: {selected}")
        from shuxin.voice.payment_config import get_payment_plan as get_plan_fallback

        return get_plan_fallback(selected)

    async def create_payment_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        plan_id = str(payload.get("plan_id") or payload.get("id") or "").strip()
        name = str(payload.get("name") or "").strip()
        amount_fen = int(payload.get("amount_fen") or 0)
        if not plan_id or not name:
            raise ValueError("plan_id and name are required")
        if amount_fen <= 0:
            raise ValueError("amount_fen must be positive")
        row = await self.pool.fetchrow(
            """
            INSERT INTO payment_plans (
                plan_id, name, description, amount_fen, sort_order, enabled, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, now())
            RETURNING plan_id, name, description, amount_fen, sort_order, enabled
            """,
            plan_id,
            name,
            str(payload.get("description") or ""),
            amount_fen,
            int(payload.get("sort_order") or 0),
            bool(payload.get("enabled", True)),
        )
        await self.audit("create_payment_plan", "payment_plan", plan_id, {"name": name})
        return plan_from_row(row).to_admin_dict()

    async def update_payment_plan(self, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        selected = str(plan_id or "").strip()
        existing = await self.pool.fetchrow(
            "SELECT plan_id FROM payment_plans WHERE plan_id = $1",
            selected,
        )
        if existing is None:
            raise ValueError(f"payment plan not found: {selected}")
        name = payload.get("name")
        description = payload.get("description")
        amount_fen = payload.get("amount_fen")
        sort_order = payload.get("sort_order")
        enabled = payload.get("enabled")
        row = await self.pool.fetchrow(
            """
            UPDATE payment_plans
            SET name = COALESCE($2, name),
                description = COALESCE($3, description),
                amount_fen = COALESCE($4, amount_fen),
                sort_order = COALESCE($5, sort_order),
                enabled = COALESCE($6, enabled),
                updated_at = now()
            WHERE plan_id = $1
            RETURNING plan_id, name, description, amount_fen, sort_order, enabled
            """,
            selected,
            str(name).strip() if name is not None else None,
            str(description) if description is not None else None,
            int(amount_fen) if amount_fen is not None else None,
            int(sort_order) if sort_order is not None else None,
            bool(enabled) if enabled is not None else None,
        )
        await self.audit("update_payment_plan", "payment_plan", selected, payload)
        return plan_from_row(row).to_admin_dict()

    async def soft_delete_payment_plan(self, plan_id: str) -> dict[str, Any]:
        selected = str(plan_id or "").strip()
        row = await self.pool.fetchrow(
            """
            UPDATE payment_plans
            SET enabled = false, updated_at = now()
            WHERE plan_id = $1
            RETURNING plan_id, name, description, amount_fen, sort_order, enabled
            """,
            selected,
        )
        if row is None:
            raise ValueError(f"payment plan not found: {selected}")
        await self.audit("disable_payment_plan", "payment_plan", selected, {})
        return plan_from_row(row).to_admin_dict()

    async def _get_display_balance(self, metadata: dict[str, Any]) -> float:
        return round(float(metadata.get(DISPLAY_BALANCE_METADATA_KEY) or 0), 4)

    async def _persist_display_balance(self, conn, user_id: str, metadata: dict[str, Any], amount: float) -> None:
        metadata[DISPLAY_BALANCE_METADATA_KEY] = round(max(float(amount), 0), 4)
        await conn.execute(
            """
            UPDATE users
            SET metadata = $2::jsonb, updated_at = now()
            WHERE user_id = $1 AND deleted_at IS NULL
            """,
            user_id,
            json.dumps(metadata, ensure_ascii=False),
        )

    async def _add_display_balance(self, conn, user_id: str, *, delta: float, metadata: dict[str, Any]) -> float:
        current = await self._get_display_balance(metadata)
        updated = round(current + float(delta), 4)
        await self._persist_display_balance(conn, user_id, metadata, updated)
        return updated

    async def get_device_quota(
        self, device_id: str, *, admin_detail: bool = False
    ) -> dict[str, Any]:
        row = await self.pool.fetchrow(
            """
            SELECT subscription_plan_id, subscription_minutes_limit, subscription_minutes_used,
                   subscription_expires_at, fuel_minutes_balance, last_reset_month,
                   daily_allowance_date, daily_allowance_seconds_used
            FROM devices
            WHERE device_id = $1
            """,
            device_id,
        )
        if row is None:
            return {
                "device_id": device_id,
                "configured": True,
                "exhausted": True,
                "remain_yuan": 0.0,
                "total_minutes_left": 0.0,
                "subscription_minutes_left": 0.0,
                "fuel_minutes_left": 0.0,
                "daily_allowance_left": 0.0,
                "subscription_expires_at": None,
                "unlimited_quota": False,
                "message": QUOTA_EXHAUSTED_MESSAGE,
            }

        # 1. 跨月惰性重置
        subscription_minutes_limit = float(row["subscription_minutes_limit"] or 0)
        subscription_minutes_used = float(row["subscription_minutes_used"] or 0.0)
        subscription_expires_at = row["subscription_expires_at"]
        fuel_minutes_balance = float(row["fuel_minutes_balance"] or 0.0)
        last_reset_month = str(row["last_reset_month"] or "").strip()
        daily_allowance_date = row["daily_allowance_date"]
        daily_allowance_seconds_used = float(row["daily_allowance_seconds_used"] or 0.0)

        from datetime import datetime, timezone
        now_dt = datetime.now(timezone.utc)
        current_month_str = now_dt.strftime("%Y-%m")

        if last_reset_month != current_month_str:
            subscription_minutes_used = 0.0
            fuel_minutes_balance = 0.0
            last_reset_month = current_month_str
            # 执行更新
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE devices
                    SET subscription_minutes_used = 0.0000,
                        fuel_minutes_balance = 0.0000,
                        last_reset_month = $2,
                        updated_at = now()
                    WHERE device_id = $1
                    """,
                    device_id,
                    current_month_str,
                )

        # 2. 计算订阅剩余分钟数
        is_sub_valid = (subscription_expires_at is not None and subscription_expires_at > now_dt)
        sub_remaining = max(0.0, subscription_minutes_limit - subscription_minutes_used) if is_sub_valid else 0.0

        # 3. 计算加油包剩余分钟数
        fuel_remaining = fuel_minutes_balance

        # 4. 计算今日低保剩余分钟数
        allowance_row = await self.pool.fetchrow(
            "SELECT daily_free_minutes, enabled FROM miniapp_allowance_settings WHERE id = 1"
        )
        daily_free_minutes = 1.5
        allowance_enabled = True
        if allowance_row is not None:
            daily_free_minutes = float(allowance_row["daily_free_minutes"])
            allowance_enabled = bool(allowance_row["enabled"])

        allowance_remaining = 0.0
        if allowance_enabled:
            today = now_dt.date()
            if daily_allowance_date != today:
                allowance_remaining = daily_free_minutes
            else:
                allowance_limit_seconds = daily_free_minutes * 60.0
                rem_seconds = max(0.0, allowance_limit_seconds - daily_allowance_seconds_used)
                allowance_remaining = rem_seconds / 60.0

        # 5. 总剩余分钟数
        total_minutes_left = sub_remaining + fuel_remaining + allowance_remaining

        # 6. 向后兼容：把总分钟数映射为 remain_yuan 返回，支持旧小程序正常显示数值
        effective_display = round(total_minutes_left, 2)
        display_exhausted = effective_display <= 0

        # 7. 获取绑定用户，同时拉取底层 DMX 状态（如果配置了）
        bound_row = await self.pool.fetchrow(
            """
            SELECT user_id FROM device_bindings
            WHERE device_id = $1 AND status = 'active'
            ORDER BY bound_at DESC LIMIT 1
            """,
            device_id
        )
        user_id = bound_row["user_id"] if bound_row else None
        
        api_key = ""
        credit_ratio = 1.0
        dmx_exhausted = False
        dmx_remain_yuan = None
        used_yuan = None
        if user_id:
            user_row = await self.pool.fetchrow("SELECT llm_config FROM users WHERE user_id = $1 AND enabled = true", user_id)
            if user_row:
                api_key = str(_json_obj(user_row["llm_config"]).get("api_key") or "").strip()
                if api_key:
                    try:
                        balance = await get_token_balance(api_key)
                        dmx_remain_yuan = balance.get("remain_yuan")
                        used_yuan = balance.get("used_yuan")
                        dmx_exhausted = bool(balance.get("exhausted"))
                        credit_ratio = await self.get_credit_ratio()
                    except Exception as exc:
                        logger.warning("DMX balance query failed during quota check for device %s: %s", device_id, exc)

        exhausted = display_exhausted or dmx_exhausted

        result = {
            "device_id": device_id,
            "configured": True,
            "exhausted": exhausted,
            "remain_yuan": effective_display, # 返回剩余分钟数
            "total_minutes_left": effective_display,
            "subscription_minutes_left": round(sub_remaining, 2),
            "fuel_minutes_left": round(fuel_remaining, 2),
            "daily_allowance_left": round(allowance_remaining, 2),
            "subscription_expires_at": _dt(subscription_expires_at) if subscription_expires_at else None,
            "unlimited_quota": False,
            "message": QUOTA_EXHAUSTED_MESSAGE if exhausted else "",
        }
        if admin_detail:
            result["display_balance_yuan"] = effective_display
            result["dmx_remain_yuan"] = dmx_remain_yuan
            result["credit_ratio"] = credit_ratio
        return result

    async def get_user_quota_by_user_id(
        self, user_id: str, *, admin_detail: bool = False
    ) -> dict[str, Any]:
        selected_id = validate_user_id(user_id)
        # Find the latest active bound device for this user
        row = await self.pool.fetchrow(
            """
            SELECT d.device_id
            FROM devices d
            JOIN device_bindings b ON b.device_id = d.device_id AND b.status = 'active'
            WHERE b.user_id = $1
            ORDER BY b.bound_at DESC
            LIMIT 1
            """,
            selected_id,
        )
        if row is not None:
            return await self.get_device_quota(row["device_id"], admin_detail=admin_detail)
        
        # Fallback: if no active bound device, return default exhausted quota
        return {
            "user_id": selected_id,
            "configured": True,
            "exhausted": True,
            "remain_yuan": 0.0,
            "total_minutes_left": 0.0,
            "subscription_minutes_left": 0.0,
            "fuel_minutes_left": 0.0,
            "daily_allowance_left": 0.0,
            "subscription_expires_at": None,
            "unlimited_quota": False,
            "message": QUOTA_EXHAUSTED_MESSAGE,
        }

    async def assert_device_quota_available(self, device_id: str) -> None:
        quota = await self.get_device_quota(device_id)
        if quota.get("exhausted"):
            raise PermissionError(QUOTA_EXHAUSTED_MESSAGE)
        remain = quota.get("remain_yuan")
        if remain is not None and float(remain) <= 0:
            raise PermissionError(QUOTA_EXHAUSTED_MESSAGE)

    async def get_user_quota_by_session(self, session_token: str) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            user_id = await self._user_id_from_wechat_auth(conn, session_token=session_token)
        return await self.get_user_quota_by_user_id(user_id)

    async def get_user_profile_by_session(self, session_token: str) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            user_id = await self._user_id_from_wechat_auth(conn, session_token=session_token)
            row = await conn.fetchrow(
                """
                SELECT metadata
                FROM users
                WHERE user_id = $1 AND deleted_at IS NULL AND enabled = true
                """,
                user_id,
            )
        if row is None:
            raise PermissionError("user is disabled or not found")
        meta = _json_obj(row["metadata"])
        quota = await self.get_user_quota_by_user_id(user_id)
        quota_payload = {key: value for key, value in quota.items() if key != "user_id"}
        return {
            "user_id": user_id,
            "roles": {
                "factory_qa": str(meta.get("factory_role") or "").lower() == "true",
            },
            "quota": quota_payload,
        }

    async def assert_user_quota_available(self, user_id: str) -> None:
        quota = await self.get_user_quota_by_user_id(user_id)
        if not quota.get("configured"):
            return
        if quota.get("exhausted"):
            raise PermissionError(QUOTA_EXHAUSTED_MESSAGE)
        remain = quota.get("remain_yuan")
        if remain is not None and float(remain) <= 0:
            raise PermissionError(QUOTA_EXHAUSTED_MESSAGE)

    async def top_up_user_dmx_quota(
        self,
        user_id: str,
        *,
        add_yuan: float,
        note: str = "",
    ) -> dict[str, Any]:
        selected_id = validate_user_id(user_id)
        amount = float(add_yuan)
        if amount <= 0:
            raise ValueError("add_yuan must be positive")
        if amount > MAX_TOP_UP_YUAN:
            raise ValueError(f"add_yuan must not exceed {MAX_TOP_UP_YUAN}")

        row = await self.pool.fetchrow(
            """
            SELECT llm_config, quota_note, metadata
            FROM users
            WHERE user_id = $1 AND deleted_at IS NULL AND enabled = true
            """,
            selected_id,
        )
        if row is None:
            raise PermissionError("user is disabled or not found")
        api_key = str(_json_obj(row["llm_config"]).get("api_key") or "").strip()
        if not api_key:
            raise PermissionError("user has no DMX api_key; ask user to login first")

        credit_ratio = await self.get_credit_ratio()
        display_credit = round(amount, 4)
        dmx_credit = round(amount * credit_ratio, 4)
        metadata = _json_obj(row["metadata"])
        async with self.pool.acquire() as conn:
            await self._add_display_balance(
                conn,
                selected_id,
                delta=display_credit,
                metadata=metadata,
            )
        top_up_result = await top_up_token_by_api_key(api_key=api_key, add_yuan=dmx_credit)
        note_text = str(note or "").strip()
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        line = f"{stamp} +{display_credit:g}元(用户)/{dmx_credit:g}元(DMX) admin"
        if note_text:
            line = f"{line} {note_text}"
        existing_note = str(row["quota_note"] or "").strip()
        merged_note = f"{existing_note}\n{line}".strip() if existing_note else line
        await self.pool.execute(
            """
            UPDATE users
            SET quota_note = $2, updated_at = now()
            WHERE user_id = $1 AND deleted_at IS NULL
            """,
            selected_id,
            merged_note,
        )

        await self.audit(
            "dmx_top_up",
            "user",
            selected_id,
            {
                "add_yuan": display_credit,
                "display_credited": display_credit,
                "dmx_credited": dmx_credit,
                "credit_ratio": credit_ratio,
                "note": note_text,
                **top_up_result,
            },
        )
        quota = await self.get_user_quota_by_user_id(selected_id, admin_detail=True)
        quota["add_yuan"] = display_credit
        quota["dmx_credited"] = dmx_credit
        return quota

    async def create_payment_order(
        self,
        *,
        session_token: str,
        plan_id: str,
        device_id: str | None = None,
    ) -> dict[str, Any]:
        # Try finding in miniapp subscription plans
        async with self.pool.acquire() as conn:
            plan_row = await conn.fetchrow(
                "SELECT name, amount_fen, duration_minutes FROM miniapp_subscription_plans WHERE plan_id = $1",
                plan_id
            )
            is_miniapp_plan = False
            if plan_row:
                is_miniapp_plan = True
                plan_name = plan_row["name"]
                amount_fen = plan_row["amount_fen"]
                duration_days = 30
            else:
                # Try finding in miniapp fuel packages
                plan_row = await conn.fetchrow(
                    "SELECT name, amount_fen, duration_minutes FROM miniapp_fuel_packages WHERE package_id = $1",
                    plan_id
                )
                if plan_row:
                    is_miniapp_plan = True
                    plan_name = plan_row["name"]
                    amount_fen = plan_row["amount_fen"]
                    duration_days = 0

        if is_miniapp_plan:
            pay_yuan = float(amount_fen) / 100.0
            display_credit = 0.0
            dmx_credit = 0.0
            credit_ratio = 1.0
            # add_yuan must satisfy CHECK (add_yuan > 0); not DMX credit for miniapp orders.
            miniapp_add_yuan = pay_yuan
            async with self.pool.acquire() as conn:
                user_id = await self._user_id_from_wechat_auth(conn, session_token=session_token)
                target_device_id = device_id
                if not target_device_id:
                    dev_row = await conn.fetchrow(
                        """
                        SELECT device_id FROM device_bindings
                        WHERE user_id = $1 AND status = 'active'
                        ORDER BY bound_at DESC LIMIT 1
                        """,
                        user_id
                    )
                    if dev_row:
                        target_device_id = dev_row["device_id"]

                if duration_days > 0 and target_device_id:
                    dev_quota = await conn.fetchrow(
                        """
                        SELECT subscription_plan_id, subscription_expires_at
                        FROM devices
                        WHERE device_id = $1
                        """,
                        target_device_id
                    )
                    if dev_quota:
                        sub_plan_id = dev_quota["subscription_plan_id"]
                        sub_expires_at = dev_quota["subscription_expires_at"]
                        from datetime import datetime, timezone
                        if sub_plan_id == plan_id and sub_expires_at is not None and sub_expires_at > datetime.now(timezone.utc):
                            raise PermissionError("您已拥有该月度套餐，在有效期内无法重复购买。")

                order_id = uuid.uuid4().hex
                out_trade_no = f"sx{uuid.uuid4().hex[:28]}"
                row = await conn.fetchrow(
                    """
                    INSERT INTO payment_orders (
                        order_id, user_id, out_trade_no, plan_id, plan_name,
                        amount_fen, add_yuan, duration_days, status,
                        pay_yuan, display_credited, dmx_credited, credit_ratio,
                        device_id
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'pending', $9, $10, $11, $12, $13)
                    RETURNING order_id, out_trade_no, plan_id, plan_name, amount_fen, add_yuan,
                              duration_days, status, created_at, pay_yuan, display_credited,
                              dmx_credited, credit_ratio, device_id
                    """,
                    order_id,
                    user_id,
                    out_trade_no,
                    plan_id,
                    plan_name,
                    amount_fen,
                    miniapp_add_yuan,
                    duration_days,
                    pay_yuan,
                    0.0,
                    0.0,
                    credit_ratio,
                    target_device_id,
                )
            return {
                "order_id": str(row["order_id"]),
                "user_id": user_id,
                "device_id": target_device_id,
                "out_trade_no": str(row["out_trade_no"]),
                "plan": {
                    "id": plan_id,
                    "name": plan_name,
                    "amount_fen": amount_fen,
                    "amount_yuan": pay_yuan,
                },
                "status": str(row["status"]),
                "created_at": _dt(row["created_at"]),
            }

        plan = await self.get_payment_plan(plan_id)
        credit_ratio = await self.get_credit_ratio()
        pay_yuan, display_credit, dmx_credit = compute_payment_credits(plan.amount_fen, credit_ratio)
        async with self.pool.acquire() as conn:
            user_id = await self._user_id_from_wechat_auth(conn, session_token=session_token)
            target_device_id = device_id
            if not target_device_id:
                dev_row = await conn.fetchrow(
                    """
                    SELECT device_id FROM device_bindings
                    WHERE user_id = $1 AND status = 'active'
                    ORDER BY bound_at DESC LIMIT 1
                    """,
                    user_id
                )
                if dev_row:
                    target_device_id = dev_row["device_id"]

            order_id = uuid.uuid4().hex
            out_trade_no = f"sx{uuid.uuid4().hex[:28]}"
            row = await conn.fetchrow(
                """
                INSERT INTO payment_orders (
                    order_id, user_id, out_trade_no, plan_id, plan_name,
                    amount_fen, add_yuan, duration_days, status,
                    pay_yuan, display_credited, dmx_credited, credit_ratio,
                    device_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, 0, 'pending', $8, $9, $10, $11, $12)
                RETURNING order_id, out_trade_no, plan_id, plan_name, amount_fen, add_yuan,
                          duration_days, status, created_at, pay_yuan, display_credited,
                          dmx_credited, credit_ratio, device_id
                """,
                order_id,
                user_id,
                out_trade_no,
                plan.id,
                plan.name,
                plan.amount_fen,
                display_credit,
                pay_yuan,
                display_credit,
                dmx_credit,
                credit_ratio,
                target_device_id,
            )
        return {
            "order_id": str(row["order_id"]),
            "user_id": user_id,
            "device_id": target_device_id,
            "out_trade_no": str(row["out_trade_no"]),
            "plan": plan.to_public_dict(),
            "status": str(row["status"]),
            "created_at": _dt(row["created_at"]),
        }

    async def attach_prepay_id(self, *, out_trade_no: str, prepay_id: str) -> None:
        await self.pool.execute(
            """
            UPDATE payment_orders
            SET wx_prepay_id = $2, updated_at = now()
            WHERE out_trade_no = $1
            """,
            out_trade_no,
            prepay_id,
        )

    async def list_payment_orders_by_session(
        self,
        session_token: str,
        *,
        limit: int = 20,
    ) -> dict[str, Any]:
        selected_limit = max(1, min(int(limit), 50))
        async with self.pool.acquire() as conn:
            user_id = await self._user_id_from_wechat_auth(conn, session_token=session_token)
            rows = await conn.fetch(
                """
                SELECT order_id, out_trade_no, plan_id, plan_name, amount_fen, add_yuan,
                       duration_days, status, wx_transaction_id, created_at, paid_at
                FROM payment_orders
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                user_id,
                selected_limit,
            )
        return {
            "user_id": user_id,
            "items": [_payment_order_item(row) for row in rows],
        }

    async def fulfill_payment_order(
        self,
        *,
        out_trade_no: str,
        wx_transaction_id: str,
        notify_payload: dict[str, Any],
    ) -> dict[str, Any]:
        selected_trade_no = str(out_trade_no or "").strip()
        if not selected_trade_no:
            raise ValueError("out_trade_no is required")
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT order_id, user_id, plan_id, plan_name, amount_fen, add_yuan,
                           duration_days, status, wx_transaction_id, pay_yuan,
                           display_credited, dmx_credited, credit_ratio, device_id
                    FROM payment_orders
                    WHERE out_trade_no = $1
                    FOR UPDATE
                    """,
                    selected_trade_no,
                )
                if row is None:
                    raise ValueError(f"payment order not found: {selected_trade_no}")
                if str(row["status"]) == "paid":
                    return {
                        "order_id": str(row["order_id"]),
                        "user_id": str(row["user_id"]),
                        "status": "paid",
                        "already_fulfilled": True,
                    }

                amount = dict(notify_payload.get("amount") or {})
                paid_total = int(amount.get("total") or 0)
                if paid_total != int(row["amount_fen"]):
                    raise ValueError(
                        f"paid amount mismatch: expected {row['amount_fen']}, got {paid_total}"
                    )

                user_id = str(row["user_id"])
                credit_ratio = float(row["credit_ratio"] or DEFAULT_CREDIT_RATIO)
                if row["display_credited"] is not None and row["dmx_credited"] is not None:
                    display_credit = float(row["display_credited"])
                    dmx_credit = float(row["dmx_credited"])
                else:
                    _, display_credit, dmx_credit = compute_payment_credits(
                        int(row["amount_fen"]),
                        credit_ratio,
                    )

                device_id = row["device_id"]
                if not device_id:
                    dev_row = await conn.fetchrow(
                        """
                        SELECT device_id FROM device_bindings
                        WHERE user_id = $1 AND status = 'active'
                        ORDER BY bound_at DESC LIMIT 1
                        """,
                        user_id
                    )
                    if dev_row:
                        device_id = dev_row["device_id"]

                # Check if it is miniapp subscription plan or fuel package
                is_miniapp_plan = False
                sub_plan_row = await conn.fetchrow(
                    "SELECT duration_minutes FROM miniapp_subscription_plans WHERE plan_id = $1",
                    row["plan_id"]
                )
                from datetime import datetime, timezone
                current_month_str = datetime.now(timezone.utc).strftime("%Y-%m")
                if device_id:
                    if sub_plan_row:
                        is_miniapp_plan = True
                        await conn.execute(
                            """
                            UPDATE devices
                            SET subscription_plan_id = $2,
                                subscription_minutes_limit = $3,
                                subscription_minutes_used = 0.0000,
                                subscription_expires_at = now() + INTERVAL '30 days',
                                last_reset_month = $4,
                                updated_at = now()
                            WHERE device_id = $1
                            """,
                            device_id,
                            row["plan_id"],
                            sub_plan_row["duration_minutes"],
                            current_month_str,
                        )
                    else:
                        fuel_pack_row = await conn.fetchrow(
                            "SELECT duration_minutes FROM miniapp_fuel_packages WHERE package_id = $1",
                            row["plan_id"]
                        )
                        if fuel_pack_row:
                            is_miniapp_plan = True
                            await conn.execute(
                                """
                                UPDATE devices
                                SET fuel_minutes_balance = COALESCE(fuel_minutes_balance, 0.0000) + $2,
                                    last_reset_month = $3,
                                    updated_at = now()
                                WHERE device_id = $1
                                """,
                                device_id,
                                float(fuel_pack_row["duration_minutes"]),
                                current_month_str,
                            )
                else:
                    if sub_plan_row or await conn.fetchrow("SELECT 1 FROM miniapp_fuel_packages WHERE package_id = $1", row["plan_id"]):
                        is_miniapp_plan = True
                        logger.warning("Fulfillment target device not found for order %s (user %s)", row["order_id"], user_id)

                top_up_result: dict[str, Any] = {}
                if not is_miniapp_plan:
                    user_row = await conn.fetchrow(
                        """
                        SELECT llm_config, quota_note, metadata
                        FROM users
                        WHERE user_id = $1 AND deleted_at IS NULL AND enabled = true
                        FOR UPDATE
                        """,
                        user_id,
                    )
                    if user_row is None:
                        raise PermissionError("user is disabled or not found")
                    api_key = str(_json_obj(user_row["llm_config"]).get("api_key") or "").strip()
                    if not api_key:
                        raise PermissionError("user has no DMX api_key; ask user to login first")

                    metadata = _json_obj(user_row["metadata"])
                    await self._add_display_balance(
                        conn,
                        user_id,
                        delta=display_credit,
                        metadata=metadata,
                    )
                    top_up_result = await top_up_token_by_api_key(api_key=api_key, add_yuan=dmx_credit)
                    note_text = f"wxpay:{selected_trade_no}"
                    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    line = f"{stamp} +{display_credit:g}元(用户)/{dmx_credit:g}元(DMX) {note_text}"
                    existing_note = str(user_row["quota_note"] or "").strip()
                    merged_note = f"{existing_note}\n{line}".strip() if existing_note else line
                    await conn.execute(
                        """
                        UPDATE users
                        SET quota_note = $2, updated_at = now()
                        WHERE user_id = $1 AND deleted_at IS NULL
                        """,
                        user_id,
                        merged_note,
                    )

                if is_miniapp_plan:
                    fulfill_add_yuan = float(row["pay_yuan"] or row["add_yuan"] or 0)
                else:
                    fulfill_add_yuan = display_credit

                await conn.execute(
                    """
                    UPDATE payment_orders
                    SET status = 'paid',
                        wx_transaction_id = $2,
                        notify_payload = $3::jsonb,
                        paid_at = now(),
                        updated_at = now(),
                        pay_yuan = $4,
                        display_credited = $5,
                        dmx_credited = $6,
                        credit_ratio = $7,
                        add_yuan = $8
                    WHERE out_trade_no = $1
                    """,
                    selected_trade_no,
                    str(wx_transaction_id or ""),
                    json.dumps(notify_payload, ensure_ascii=False),
                    float(row["pay_yuan"] or display_credit),
                    display_credit,
                    dmx_credit,
                    credit_ratio,
                    fulfill_add_yuan,
                )
        await self.audit(
            "payment_fulfilled",
            "payment_order",
            selected_trade_no,
            {
                "user_id": user_id,
                "display_credited": display_credit,
                "dmx_credited": dmx_credit,
                "credit_ratio": credit_ratio,
                "wx_transaction_id": wx_transaction_id,
                **top_up_result,
            },
        )
        return {
            "order_id": str(row["order_id"]),
            "user_id": user_id,
            "status": "paid",
            "already_fulfilled": False,
            "display_credited": display_credit,
            "dmx_credited": dmx_credit,
            "add_yuan": fulfill_add_yuan,
        }

    async def _extend_subscription(
        self,
        conn,
        *,
        user_id: str,
        duration_days: int,
    ) -> None:
        row = await conn.fetchrow(
            """
            SELECT metadata
            FROM users
            WHERE user_id = $1 AND deleted_at IS NULL
            FOR UPDATE
            """,
            user_id,
        )
        if row is None:
            return
        metadata = _json_obj(row["metadata"])
        now = datetime.now(timezone.utc)
        current_raw = str(metadata.get("subscription_expires_at") or "").strip()
        base = now
        if current_raw:
            try:
                current = datetime.fromisoformat(current_raw.replace("Z", "+00:00"))
                if current.tzinfo is None:
                    current = current.replace(tzinfo=timezone.utc)
                if current > now:
                    base = current
            except ValueError:
                base = now
        expires_at = base + timedelta(days=duration_days)
        metadata["subscription_expires_at"] = expires_at.isoformat()
        await conn.execute(
            """
            UPDATE users
            SET metadata = $2::jsonb, updated_at = now()
            WHERE user_id = $1 AND deleted_at IS NULL
            """,
            user_id,
            json.dumps(metadata, ensure_ascii=False),
        )

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
        await self.ensure_user_dmx_llm(user_id)
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

    # ------------------------------------------------------------------
    # 工厂验收
    # ------------------------------------------------------------------

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
            mbti = await self._attach_mbti_reveal_on_bind(conn, device_id)
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
            gift = await conn.fetchrow(
                """
                SELECT gift_subscription_plan_id, gift_duration_months
                FROM miniapp_allowance_settings
                WHERE id = 1
                """
            )
            if gift and gift["gift_subscription_plan_id"] and gift["gift_duration_months"] > 0:
                gift_plan_id = gift["gift_subscription_plan_id"]
                gift_months = gift["gift_duration_months"]
                plan_row = await conn.fetchrow(
                    "SELECT duration_minutes FROM miniapp_subscription_plans WHERE plan_id = $1 AND enabled = true",
                    gift_plan_id
                )
                if plan_row:
                    duration_minutes = plan_row["duration_minutes"]
                    await conn.execute(
                        """
                        UPDATE devices
                        SET subscription_plan_id = $2,
                            subscription_minutes_limit = $3,
                            subscription_minutes_used = 0.0000,
                            subscription_expires_at = now() + ($4 * INTERVAL '30 days'),
                            updated_at = now()
                        WHERE device_id = $1
                        """,
                        device_id,
                        gift_plan_id,
                        duration_minutes,
                        gift_months,
                    )

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
        mbti = await self._attach_mbti_reveal_on_bind(conn, device_id)
        if mbti:
            result["mbti"] = mbti
        return result

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
        from shuxin.voice.mbti_reveal import build_mbti_client_payload, is_mbti_locked

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
        from shuxin.voice.mbti_reveal import build_mbti_client_payload, needs_mbti_reveal

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
                    await self.audit(
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

        if not _verify_device_secret(row, device_secret or ""):
            await self._record_auth_failure(selected_code)
            raise PermissionError("invalid device secret")

        user_id = str(row["user_id"])
        await self.ensure_user_dmx_llm(user_id)
        llm_row = await self.pool.fetchrow(
            "SELECT llm_config FROM users WHERE user_id = $1 AND deleted_at IS NULL",
            user_id,
        )
        llm_config = _json_obj(llm_row["llm_config"]) if llm_row else _json_obj(row["llm_config"])

        return UserSettings(
            user_id=user_id,
            token="",
            audio_quota_mb=int(row["audio_quota_mb"]),
            llm_config=llm_config,
            agent_id=str(row["agent_id"] or ""),
        )

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
        if not _verify_device_secret(row, device_secret or ""):
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
                await self._refresh_shared_memory(
                    conn,
                    user_settings,
                    warning,
                    user_text=user_text,
                )

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

    async def maybe_merge_rolling_summary(
        self,
        user_settings: UserSettings,
        device: DeviceConfig | None,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        summary = await self.export_summary(user_settings)
        if not summary:
            summary = {"user_id": user_settings.user_id, **memory_field_defaults()}
        if not should_merge_summary(summary, force=force):
            return {"merged": False, "reason": "not_due"}
        recent_turns = await self._fetch_recent_turns(user_settings.user_id)
        loop = asyncio.get_event_loop()
        merged_text = await loop.run_in_executor(
            None,
            lambda: merge_summary_with_llm(
                device=device,
                existing_summary=str(summary.get("rolling_summary") or ""),
                recent_topics=list(summary.get("recent_topics") or []),
                recent_turns=recent_turns,
            ),
        )
        updated = finalize_summary_after_merge(summary, merged_text)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await self._persist_summary(conn, user_settings.user_id, updated)
        sync_summary_json(user_settings.user_id, updated)
        return {"merged": True, "summary_updated_at": updated.get("summary_updated_at")}

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

    async def purge_expired_audio_attachments(self, *, retention_hours: int) -> dict[str, int]:
        if retention_hours <= 0:
            return {"purged": 0, "bytes_freed": 0}
        purged = 0
        bytes_freed = 0
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    """
                    SELECT attachment_id, path, size_bytes, user_id
                    FROM audio_attachments
                    WHERE deleted_at IS NULL
                      AND created_at < now() - make_interval(hours => $1)
                    ORDER BY created_at ASC, attachment_id ASC
                    """,
                    retention_hours,
                )
                for row in rows:
                    path = Path(str(row["path"]))
                    stop_at = _user_outputs_root(path, str(row["user_id"]))
                    if path.exists():
                        bytes_freed += purge_attachment_file(path, stop_at=stop_at)
                    else:
                        bytes_freed += int(row["size_bytes"] or 0)
                    await conn.execute(
                        "UPDATE audio_attachments SET deleted_at = now() WHERE attachment_id = $1",
                        row["attachment_id"],
                    )
                    purged += 1
        return {"purged": purged, "bytes_freed": bytes_freed}

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
        await self.audit("reveal_device_secret", "device", selected_id, {"hint": hint})
        return {
            "device_id": selected_id,
            "device_secret": secret,
            "hint": hint,
        }

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
        await self.audit(
            "apply_default_tts",
            "device",
            "*",
            {"tts_type": "volcengine-clone", "updated_count": updated_count},
        )
        return {"updated_count": updated_count, "tts_type": "volcengine-clone"}

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
                'data/agents/shuxin/SOUL.md', '{"default_mbti":"INFJ"}'::jsonb
            )
            ON CONFLICT (agent_id) DO UPDATE SET
                voice_type = CASE
                    WHEN agents.voice_type = '' AND EXCLUDED.voice_type <> ''
                    THEN EXCLUDED.voice_type
                    ELSE agents.voice_type
                END,
                updated_at = now()
            """,
            voice_type,
        )
        await self.pool.execute(
            """
            UPDATE users
            SET agent_id = 'shuxin', updated_at = now()
            WHERE agent_id IS NULL AND deleted_at IS NULL
            """
        )
        invalidate_agent_cache()

    async def list_agents(
        self,
        *,
        limit: int = 50,
        cursor: str = "",
        q: str = "",
    ) -> dict[str, Any]:
        search = _search_pattern(q)
        rows = await self.pool.fetch(
            """
            SELECT agent_id, display_name, voice_type, cluster, speed_ratio, encoding,
                   uid, soul_path, initial_state, metadata, enabled, created_at, updated_at
            FROM agents
            WHERE deleted_at IS NULL
              AND ($1 = '' OR agent_id > $1)
              AND (
                $3 = ''
                OR agent_id ILIKE $3
                OR display_name ILIKE $3
                OR voice_type ILIKE $3
              )
            ORDER BY agent_id ASC
            LIMIT $2
            """,
            cursor,
            max(1, min(limit, 100)),
            search,
        )
        items = [AgentRecord.from_row(row).to_admin_dict() for row in rows]
        return {"items": items, "next_cursor": items[-1]["agent_id"] if len(items) == limit else ""}

    async def get_agent(self, agent_id: str) -> AgentRecord:
        selected = validate_user_id(agent_id)
        cached = get_cached_agent(selected)
        if cached is not None:
            return cached
        row = await self.pool.fetchrow(
            """
            SELECT agent_id, display_name, voice_type, cluster, speed_ratio, encoding,
                   uid, soul_path, initial_state, metadata, enabled
            FROM agents
            WHERE agent_id = $1 AND deleted_at IS NULL AND enabled = true
            """,
            selected,
        )
        if row is None:
            raise ValueError(f"agent not found: {selected}")
        record = AgentRecord.from_row(row)
        cache_agent(record)
        return record

    async def get_user_agent_id(self, user_id: str) -> str:
        selected = validate_user_id(user_id)
        row = await self.pool.fetchrow(
            """
            SELECT agent_id
            FROM users
            WHERE user_id = $1 AND deleted_at IS NULL AND enabled = true
            """,
            selected,
        )
        if row is None:
            raise PermissionError("user is disabled or not found")
        agent_id = str(row["agent_id"] or "").strip()
        return agent_id or DEFAULT_AGENT_ID

    async def create_agent(self, payload: dict[str, Any]) -> dict[str, Any]:
        agent_id = validate_user_id(str(payload.get("agent_id") or ""))
        voice_type = str(payload.get("voice_type") or "").strip()
        if not voice_type:
            raise ValueError("voice_type is required")
        metadata = dict(payload.get("metadata") or {})
        await self.pool.execute(
            """
            INSERT INTO agents (
                agent_id, display_name, voice_type, cluster, speed_ratio, encoding,
                uid, soul_path, initial_state, metadata, enabled, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10::jsonb, $11, now())
            ON CONFLICT (agent_id) DO UPDATE SET
                display_name = excluded.display_name,
                voice_type = excluded.voice_type,
                cluster = excluded.cluster,
                speed_ratio = excluded.speed_ratio,
                encoding = excluded.encoding,
                uid = excluded.uid,
                soul_path = excluded.soul_path,
                initial_state = excluded.initial_state,
                metadata = excluded.metadata,
                enabled = excluded.enabled,
                deleted_at = NULL,
                updated_at = now()
            """,
            agent_id,
            str(payload.get("display_name") or agent_id),
            voice_type,
            str(payload.get("cluster") or "volcano_icl"),
            float(payload.get("speed_ratio") or 1.0),
            str(payload.get("encoding") or "mp3"),
            str(payload.get("uid") or agent_id),
            str(payload.get("soul_path") or ""),
            json.dumps(payload.get("initial_state") or {}, ensure_ascii=False),
            json.dumps(metadata, ensure_ascii=False),
            bool(payload.get("enabled", True)),
        )
        invalidate_agent_cache(agent_id)
        await self.audit("create_agent", "agent", agent_id, {"display_name": payload.get("display_name")})
        record = await self.get_agent(agent_id)
        return record.to_admin_dict()

    async def update_agent(self, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        selected = validate_user_id(agent_id)
        existing = await self.pool.fetchrow(
            "SELECT * FROM agents WHERE agent_id = $1 AND deleted_at IS NULL",
            selected,
        )
        if existing is None:
            raise ValueError(f"agent not found: {selected}")
        fields: list[str] = []
        values: list[Any] = []
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
        if "agent_id" in payload:
            agent_id = str(payload.get("agent_id") or "").strip()
            if agent_id:
                await self.get_agent(agent_id)
            await self.pool.execute(
                """
                UPDATE users
                SET agent_id = $2, updated_at = now()
                WHERE user_id = $1 AND deleted_at IS NULL
                """,
                selected,
                agent_id or None,
            )
            await self.audit("patch_user_agent", "user", selected, {"agent_id": agent_id})
        if "metadata" in payload:
            new_meta = payload.get("metadata")
            if not isinstance(new_meta, dict):
                raise ValueError("metadata must be an object")
            await self.pool.execute(
                """
                UPDATE users
                SET metadata = metadata || $2::jsonb, updated_at = now()
                WHERE user_id = $1 AND deleted_at IS NULL
                """,
                selected,
                json.dumps(new_meta, ensure_ascii=False),
            )
            await self.audit("patch_user_metadata", "user", selected, {"metadata_keys": list(new_meta.keys())})
        return {"user_id": selected, "agent_id": payload.get("agent_id", "")}

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

                await self.audit(
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
                await self.audit(
                    "mark_mbti_locked",
                    "device",
                    selected_id,
                    {},
                )
        return {"device_id": selected_id, "mbti_status": "locked"}

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
                   enabled, metadata, agent_id, created_at, updated_at
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
                "agent_id": str(row["agent_id"] or ""),
                "metadata": _json_obj(row["metadata"]),
                "created_at": _dt(row["created_at"]),
                "updated_at": _dt(row["updated_at"]),
            }
            for row in rows
        ]
        return {"items": items, "next_cursor": items[-1]["user_id"] if len(items) == limit else ""}

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
        await self.audit("upsert_user", "user", user_id, _mask_secrets({**payload, "token": "***"}))
        return {"user_id": user_id}

    async def hard_delete_user_for_test(self, user_id: str) -> None:
        """测试模式真删：解绑设备、清理会话/记忆并删除 users 行。"""
        selected_id = validate_user_id(user_id)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                active_bindings = await conn.fetch(
                    """
                    SELECT device_id
                    FROM device_bindings
                    WHERE user_id = $1 AND status = 'active'
                    """,
                    selected_id,
                )
                for row in active_bindings:
                    device_id = str(row["device_id"])
                    await conn.execute(
                        """
                        UPDATE device_bindings
                        SET status = 'unbound', unbound_at = now()
                        WHERE user_id = $1 AND device_id = $2 AND status = 'active'
                        """,
                        selected_id,
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
                    await self._restore_latest_claim_code(conn, device_id)

                await conn.execute(
                    "DELETE FROM conversation_events WHERE user_id = $1",
                    selected_id,
                )
                await conn.execute(
                    "DELETE FROM audio_attachments WHERE user_id = $1",
                    selected_id,
                )
                await conn.execute(
                    "DELETE FROM voice_sessions WHERE user_id = $1",
                    selected_id,
                )
                await conn.execute(
                    "DELETE FROM wechat_sessions WHERE user_id = $1",
                    selected_id,
                )
                await conn.execute(
                    "DELETE FROM shared_memory WHERE user_id = $1",
                    selected_id,
                )
                await conn.execute(
                    "DELETE FROM user_facts WHERE user_id = $1",
                    selected_id,
                )
                await conn.execute(
                    "DELETE FROM companion_state WHERE user_id = $1",
                    selected_id,
                )
                await conn.execute(
                    "DELETE FROM device_bindings WHERE user_id = $1",
                    selected_id,
                )
                await conn.execute(
                    "DELETE FROM device_binding_events WHERE user_id = $1",
                    selected_id,
                )
                await conn.execute(
                    "DELETE FROM users WHERE user_id = $1",
                    selected_id,
                )
        await self.audit("hard_delete_user_test", "user", selected_id, {})

    async def soft_delete_user(self, user_id: str) -> None:
        selected_id = validate_user_id(user_id)
        if voice_test_mode_enabled():
            await self.hard_delete_user_for_test(selected_id)
            return
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

    async def _load_summary(self, conn, user_id: str) -> dict[str, Any]:
        row = await conn.fetchval(
            "SELECT summary FROM shared_memory WHERE user_id = $1",
            user_id,
        )
        loaded = _json_obj(row)
        if loaded:
            return loaded
        return {"user_id": user_id, **memory_field_defaults()}

    async def _persist_summary(self, conn, user_id: str, summary: dict[str, Any]) -> None:
        await conn.execute(
            """
            INSERT INTO shared_memory (user_id, summary, updated_at)
            VALUES ($1, $2::jsonb, now())
            ON CONFLICT (user_id) DO UPDATE SET
                summary = excluded.summary,
                updated_at = now()
            """,
            user_id,
            json.dumps(summary, ensure_ascii=False),
        )

    async def _fetch_recent_turns(self, user_id: str, *, limit: int = 15) -> list[dict[str, Any]]:
        rows = await self.pool.fetch(
            """
            SELECT user_text, reply_text, created_at
            FROM conversation_events
            WHERE user_id = $1
              AND deleted_at IS NULL
              AND created_at >= now() - make_interval(days => $2)
            ORDER BY created_at DESC
            LIMIT $3
            """,
            user_id,
            SUMMARY_WINDOW_DAYS,
            limit,
        )
        items = [
            {
                "user_text": row["user_text"],
                "reply_text": row["reply_text"],
                "created_at": _dt(row["created_at"]),
            }
            for row in rows
        ]
        return list(reversed(items))

    async def _refresh_shared_memory(
        self,
        conn,
        user_settings: UserSettings,
        warning: str,
        *,
        user_text: str = "",
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
        existing = await self._load_summary(conn, user_settings.user_id)
        stats = {
            "user_id": user_settings.user_id,
            "turn_count": int(event_count or 0),
            "last_interaction_at": datetime.now(timezone.utc).isoformat(),
            "audio_quota_bytes": user_settings.audio_quota_bytes,
            "audio_used_bytes": used,
            "over_quota": used > user_settings.audio_quota_bytes,
            "last_warning": warning,
            "milestones": existing.get("milestones") or [],
        }
        summary = merge_summary_with_stats(existing, stats)
        if user_text.strip():
            summary = apply_turn_to_summary(summary, user_text)
        await self._persist_summary(conn, user_settings.user_id, summary)
        sync_summary_json(user_settings.user_id, summary)

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
        async with self.pool.acquire() as conn:
            feedback_id = await conn.fetchval(
                """
                INSERT INTO feedbacks (user_id, content, contact, status)
                VALUES ($1, $2, $3, 'pending')
                RETURNING id
                """,
                user_id,
                content,
                contact,
            )
        return {"id": feedback_id, "ok": True}

    async def admin_list_feedbacks(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """管理员列表查询用户反馈。"""
        async with self.pool.acquire() as conn:
            if status:
                rows = await conn.fetch(
                    """
                    SELECT id, user_id, content, contact, created_at, status, admin_notes
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
                    SELECT id, user_id, content, contact, created_at, status, admin_notes
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
                "contact": row["contact"],
                "created_at": _dt(row["created_at"]),
                "status": row["status"],
                "admin_notes": row["admin_notes"],
            }
            for row in rows
        ]

    async def admin_update_feedback(
        self,
        feedback_id: int,
        *,
        status: str,
        admin_notes: str,
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

    # === 小程序订阅套餐管理 ===
    async def admin_list_subscription_plans(self) -> list[dict[str, Any]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT plan_id, name, amount_fen, duration_minutes, description, sort_order, enabled, created_at, updated_at
                FROM miniapp_subscription_plans
                ORDER BY sort_order ASC, plan_id ASC
                """
            )
        return [
            {
                "plan_id": row["plan_id"],
                "name": row["name"],
                "amount_fen": row["amount_fen"],
                "amount_yuan": round(row["amount_fen"] / 100, 2),
                "duration_minutes": row["duration_minutes"],
                "description": row["description"],
                "sort_order": row["sort_order"],
                "enabled": row["enabled"],
                "created_at": _dt(row["created_at"]),
                "updated_at": _dt(row["updated_at"]),
            }
            for row in rows
        ]

    async def admin_upsert_subscription_plan(
        self,
        *,
        plan_id: str,
        name: str,
        amount_fen: int,
        duration_minutes: int,
        description: str = "",
        sort_order: int = 0,
        enabled: bool = True,
    ) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO miniapp_subscription_plans (
                    plan_id, name, amount_fen, duration_minutes, description, sort_order, enabled, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, now())
                ON CONFLICT (plan_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    amount_fen = EXCLUDED.amount_fen,
                    duration_minutes = EXCLUDED.duration_minutes,
                    description = EXCLUDED.description,
                    sort_order = EXCLUDED.sort_order,
                    enabled = EXCLUDED.enabled,
                    updated_at = now()
                """,
                plan_id,
                name,
                amount_fen,
                duration_minutes,
                description,
                sort_order,
                enabled,
            )
        return {"plan_id": plan_id, "ok": True}

    async def admin_delete_subscription_plan(self, plan_id: str) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM miniapp_subscription_plans WHERE plan_id = $1",
                plan_id,
            )
        return {"ok": result.endswith("1")}

    # === 小程序充值加油包管理 ===
    async def admin_list_fuel_packages(self) -> list[dict[str, Any]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT package_id, name, amount_fen, duration_minutes, description, sort_order, enabled, created_at, updated_at
                FROM miniapp_fuel_packages
                ORDER BY sort_order ASC, package_id ASC
                """
            )
        return [
            {
                "package_id": row["package_id"],
                "name": row["name"],
                "amount_fen": row["amount_fen"],
                "amount_yuan": round(row["amount_fen"] / 100, 2),
                "duration_minutes": row["duration_minutes"],
                "description": row["description"],
                "sort_order": row["sort_order"],
                "enabled": row["enabled"],
                "created_at": _dt(row["created_at"]),
                "updated_at": _dt(row["updated_at"]),
            }
            for row in rows
        ]

    async def admin_upsert_fuel_package(
        self,
        *,
        package_id: str,
        name: str,
        amount_fen: int,
        duration_minutes: int,
        description: str = "",
        sort_order: int = 0,
        enabled: bool = True,
    ) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO miniapp_fuel_packages (
                    package_id, name, amount_fen, duration_minutes, description, sort_order, enabled, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, now())
                ON CONFLICT (package_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    amount_fen = EXCLUDED.amount_fen,
                    duration_minutes = EXCLUDED.duration_minutes,
                    description = EXCLUDED.description,
                    sort_order = EXCLUDED.sort_order,
                    enabled = EXCLUDED.enabled,
                    updated_at = now()
                """,
                package_id,
                name,
                amount_fen,
                duration_minutes,
                description,
                sort_order,
                enabled,
            )
        return {"package_id": package_id, "ok": True}

    async def admin_delete_fuel_package(self, package_id: str) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM miniapp_fuel_packages WHERE package_id = $1",
                package_id,
            )
        return {"ok": result.endswith("1")}

    # === 小程序每日低保管理 ===
    async def admin_get_allowance_settings(self) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT daily_free_minutes, enabled, gift_subscription_plan_id, gift_duration_months
                FROM miniapp_allowance_settings
                WHERE id = 1
                """
            )
        if row is None:
            return {
                "daily_free_minutes": 1.5,
                "enabled": True,
                "gift_subscription_plan_id": None,
                "gift_duration_months": 0,
            }
        return {
            "daily_free_minutes": float(row["daily_free_minutes"]),
            "enabled": bool(row["enabled"]),
            "gift_subscription_plan_id": row["gift_subscription_plan_id"],
            "gift_duration_months": int(row["gift_duration_months"] or 0),
        }

    async def admin_update_allowance_settings(
        self,
        *,
        daily_free_minutes: float,
        enabled: bool,
        gift_subscription_plan_id: str | None = None,
        gift_duration_months: int = 0,
    ) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO miniapp_allowance_settings (
                    id, daily_free_minutes, enabled, gift_subscription_plan_id, gift_duration_months, updated_at
                )
                VALUES (1, $1, $2, $3, $4, now())
                ON CONFLICT (id) DO UPDATE SET
                    daily_free_minutes = EXCLUDED.daily_free_minutes,
                    enabled = EXCLUDED.enabled,
                    gift_subscription_plan_id = EXCLUDED.gift_subscription_plan_id,
                    gift_duration_months = EXCLUDED.gift_duration_months,
                    updated_at = now()
                """,
                daily_free_minutes,
                enabled,
                gift_subscription_plan_id,
                gift_duration_months,
            )
        return {"ok": True}

    # === 扣减设备分钟额度 (状态机) ===
    async def deduct_device_minutes_quota(self, device_id: str, cost_minutes: float) -> None:
        """从设备的月度订阅、加油包和低保额度中扣除会话分钟数（高精度）。"""
        if cost_minutes <= 0:
            return

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # 获取设备当前额度状态
                row = await conn.fetchrow(
                    """
                    SELECT subscription_plan_id, subscription_minutes_limit, subscription_minutes_used,
                           subscription_expires_at, fuel_minutes_balance, last_reset_month,
                           daily_allowance_date, daily_allowance_seconds_used
                    FROM devices
                    WHERE device_id = $1
                    FOR UPDATE
                    """,
                    device_id,
                )
                if row is None:
                    return

                subscription_plan_id = row["subscription_plan_id"]
                subscription_minutes_limit = float(row["subscription_minutes_limit"] or 0)
                subscription_minutes_used = float(row["subscription_minutes_used"] or 0.0)
                subscription_expires_at = row["subscription_expires_at"]
                fuel_minutes_balance = float(row["fuel_minutes_balance"] or 0.0)
                last_reset_month = str(row["last_reset_month"] or "").strip()
                daily_allowance_date = row["daily_allowance_date"]
                daily_allowance_seconds_used = float(row["daily_allowance_seconds_used"] or 0.0)

                from datetime import datetime, timezone
                now_dt = datetime.now(timezone.utc)
                current_month_str = now_dt.strftime("%Y-%m")

                # 1. 跨月惰性重置
                if last_reset_month != current_month_str:
                    subscription_minutes_used = 0.0
                    fuel_minutes_balance = 0.0
                    last_reset_month = current_month_str
                    await conn.execute(
                        """
                        UPDATE devices
                        SET subscription_minutes_used = 0.0000,
                            fuel_minutes_balance = 0.0000,
                            last_reset_month = $2,
                            updated_at = now()
                        WHERE device_id = $1
                        """,
                        device_id,
                        current_month_str,
                    )

                # 2. 判断订阅是否有效（未过期）
                is_sub_valid = (subscription_expires_at is not None and subscription_expires_at > now_dt)

                # 3. 优先级扣减：订阅额度 -> 加油包 -> 每日低保
                remaining_cost = cost_minutes

                # 3.1 订阅额度扣减
                if is_sub_valid:
                    sub_rem = max(0.0, subscription_minutes_limit - subscription_minutes_used)
                    if sub_rem > 0:
                        if sub_rem >= remaining_cost:
                            subscription_minutes_used += remaining_cost
                            remaining_cost = 0.0
                        else:
                            subscription_minutes_used = subscription_minutes_limit
                            remaining_cost -= sub_rem

                # 3.2 加油包扣减
                if remaining_cost > 0 and fuel_minutes_balance > 0:
                    if fuel_minutes_balance >= remaining_cost:
                        fuel_minutes_balance -= remaining_cost
                        remaining_cost = 0.0
                    else:
                        remaining_cost -= fuel_minutes_balance
                        fuel_minutes_balance = 0.0

                # 3.3 每日温情低保扣减
                if remaining_cost > 0:
                    # 获取全局低保设置
                    allowance_row = await conn.fetchrow(
                        "SELECT daily_free_minutes, enabled FROM miniapp_allowance_settings WHERE id = 1"
                    )
                    daily_free_minutes = 1.5
                    allowance_enabled = True
                    if allowance_row is not None:
                        daily_free_minutes = float(allowance_row["daily_free_minutes"])
                        allowance_enabled = bool(allowance_row["enabled"])

                    if allowance_enabled:
                        today = now_dt.date()
                        if daily_allowance_date != today:
                            daily_allowance_date = today
                            daily_allowance_seconds_used = 0.0

                        cost_seconds = remaining_cost * 60.0
                        allowance_limit_seconds = daily_free_minutes * 60.0
                        rem_seconds = max(0.0, allowance_limit_seconds - daily_allowance_seconds_used)

                        if rem_seconds >= cost_seconds:
                            daily_allowance_seconds_used += cost_seconds
                            remaining_cost = 0.0
                        else:
                            daily_allowance_seconds_used = allowance_limit_seconds
                            remaining_cost -= (rem_seconds / 60.0)

                # 更新设备额度列到数据库
                await conn.execute(
                    """
                    UPDATE devices
                    SET subscription_minutes_used = $2,
                        fuel_minutes_balance = $3,
                        last_reset_month = $4,
                        daily_allowance_date = $5,
                        daily_allowance_seconds_used = $6,
                        updated_at = now()
                    WHERE device_id = $1
                    """,
                    device_id,
                    subscription_minutes_used,
                    fuel_minutes_balance,
                    last_reset_month,
                    daily_allowance_date,
                    daily_allowance_seconds_used,
                )

    async def get_pricing_by_type(self, service_type: str) -> dict[str, float]:
        row = await self.pool.fetchrow(
            """
            SELECT value
            FROM platform_settings
            WHERE key = $1
            """,
            f"pricing.{service_type}",
        )
        if row is None:
            return {}
        payload = _json_obj(row["value"])
        return {str(k): float(v) for k, v in payload.items()}

    async def insert_expenditure(
        self,
        *,
        user_id: str,
        service_type: str,
        model_name: str,
        usage_amount: float,
        cost_yuan: float,
    ) -> None:
        import uuid
        await self.pool.execute(
            """
            INSERT INTO user_expenditures (
                expenditure_id, user_id, type, model, usage_amount, cost_yuan, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, now())
            """,
            uuid.uuid4().hex,
            user_id,
            service_type,
            model_name,
            usage_amount,
            cost_yuan,
        )

    async def get_monthly_expenditure_summary(self, month_str: str) -> dict[str, Any]:
        rows = await self.pool.fetch(
            """
            SELECT type, COALESCE(SUM(cost_yuan), 0) as cost
            FROM user_expenditures
            WHERE TO_CHAR(created_at, 'YYYY-MM') = $1
            GROUP BY type
            """,
            month_str,
        )
        
        turns_row = await self.pool.fetchrow(
            """
            SELECT COUNT(DISTINCT turn_id) as turns
            FROM conversation_events
            WHERE TO_CHAR(created_at, 'YYYY-MM') = $1
              AND deleted_at IS NULL
            """,
            month_str,
        )
        total_turns = int(turns_row["turns"] or 0) if turns_row else 0

        breakdown = {
            "llm": {"cost": 0.0, "percentage": 0.0},
            "stt": {"cost": 0.0, "percentage": 0.0},
            "tts": {"cost": 0.0, "percentage": 0.0},
        }
        total_cost = 0.0
        for row in rows:
            t = str(row["type"])
            cost = float(row["cost"] or 0.0)
            if t in breakdown:
                breakdown[t]["cost"] = cost
            total_cost += cost

        if total_cost > 0:
            for t in breakdown:
                breakdown[t]["percentage"] = round((breakdown[t]["cost"] / total_cost) * 100, 2)

        average_turn_cost = round(total_cost / total_turns, 4) if total_turns > 0 else 0.0

        return {
            "total_cost": round(total_cost, 4),
            "breakdown": breakdown,
            "total_turns": total_turns,
            "average_turn_cost": average_turn_cost,
        }

    async def list_expenditures(
        self,
        *,
        month_str: str,
        user_id: str = "",
        limit: int = 50,
        cursor: str = "",
    ) -> dict[str, Any]:
        offset = 0
        if cursor:
            try:
                offset = int(cursor)
            except ValueError:
                pass

        query_limit = max(1, min(limit, 100))
        
        if user_id:
            rows = await self.pool.fetch(
                """
                SELECT expenditure_id, user_id, type, model, usage_amount, cost_yuan, created_at
                FROM user_expenditures
                WHERE TO_CHAR(created_at, 'YYYY-MM') = $1
                  AND user_id = $2
                ORDER BY created_at DESC, expenditure_id DESC
                LIMIT $3 OFFSET $4
                """,
                month_str,
                user_id,
                query_limit,
                offset,
            )
        else:
            rows = await self.pool.fetch(
                """
                SELECT expenditure_id, user_id, type, model, usage_amount, cost_yuan, created_at
                FROM user_expenditures
                WHERE TO_CHAR(created_at, 'YYYY-MM') = $1
                ORDER BY created_at DESC, expenditure_id DESC
                LIMIT $2 OFFSET $3
                """,
                month_str,
                query_limit,
                offset,
            )

        items = []
        for row in rows:
            items.append({
                "id": str(row["expenditure_id"]),
                "user_id": str(row["user_id"]),
                "type": str(row["type"]),
                "model": str(row["model"]),
                "usage_amount": float(row["usage_amount"]),
                "cost_yuan": float(row["cost_yuan"]),
                "created_at": _dt(row["created_at"]),
            })

        next_cursor = ""
        if len(items) == query_limit:
            next_cursor = str(offset + query_limit)

        return {
            "items": items,
            "next_cursor": next_cursor,
        }

    async def delete_expenditure(self, expenditure_id: str) -> bool:
        result = await self.pool.execute(
            """
            DELETE FROM user_expenditures
            WHERE expenditure_id = $1
            """,
            expenditure_id,
        )
        return result.endswith("1")

    async def delete_monthly_expenditures(self, month_str: str) -> int:
        result = await self.pool.execute(
            """
            DELETE FROM user_expenditures
            WHERE TO_CHAR(created_at, 'YYYY-MM') = $1
            """,
            month_str,
        )
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0

    async def get_all_pricing(self) -> dict[str, Any]:
        rows = await self.pool.fetch(
            """
            SELECT key, value
            FROM platform_settings
            WHERE key IN ('pricing.stt', 'pricing.tts', 'pricing.llm')
            """
        )
        result = {"stt": {}, "tts": {}, "llm": {}}
        for row in rows:
            k = str(row["key"])
            val = _json_obj(row["value"])
            t = k.split(".")[-1]
            if t in result:
                result[t] = {str(name): float(price) for name, price in val.items()}
        return result

    async def update_pricing(self, pricing_type: str, pricing_dict: dict[str, float]) -> None:
        if pricing_type not in ("stt", "tts", "llm"):
            raise ValueError(f"Invalid pricing type: {pricing_type}")
        
        cleaned = {str(k): float(v) for k, v in pricing_dict.items()}
        await self.pool.execute(
            """
            INSERT INTO platform_settings (key, value, updated_at)
            VALUES ($1, $2::jsonb, now())
            ON CONFLICT (key) DO UPDATE SET
                value = excluded.value,
                updated_at = now()
            """,
            f"pricing.{pricing_type}",
            json.dumps(cleaned, ensure_ascii=False),
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
                "stt": default_tencent_stt_config(),
                "tts": default_device_tts_config(),
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


def _payment_order_item(row: Any) -> dict[str, Any]:
    return {
        "order_id": str(row["order_id"]),
        "out_trade_no": str(row["out_trade_no"]),
        "plan_id": str(row["plan_id"]),
        "plan_name": str(row["plan_name"]),
        "amount_fen": int(row["amount_fen"]),
        "amount_yuan": round(int(row["amount_fen"]) / 100, 2),
        "add_yuan": float(row["add_yuan"]),
        "duration_days": int(row["duration_days"] or 0),
        "status": str(row["status"]),
        "wx_transaction_id": str(row["wx_transaction_id"] or ""),
        "created_at": _dt(row["created_at"]),
        "paid_at": _dt(row["paid_at"]) if row["paid_at"] else "",
    }


def _dt(value: Any) -> str:
    return format_beijing_display(value)


def _dt_iso(value: Any) -> str:
    return format_beijing_iso(value)


def _device_row(row) -> dict[str, Any]:
    auth_mode = str(row["auth_mode"] or "shared_secret")
    secret, secret_hint = resolve_stored_device_secret(
        auth_mode=auth_mode,
        device_secret_encrypted=str(row.get("device_secret_encrypted") or "") or None,
    )
    return {
        "device_id": str(row["device_id"]),
        "device_code": str(row["device_id"]),
        "auth_mode": auth_mode,
        "device_secret_configured": bool(row["device_secret_hash"])
        or auth_mode == "shared_secret",
        "device_secret_masked": mask_device_secret(secret) if secret else "",
        "device_secret_retrievable": bool(secret),
        "device_secret_hint": secret_hint,
        "lifecycle_status": str(row.get("lifecycle_status") or "provisioned"),
        "bound_user_id": str(row.get("bound_user_id") or ""),
        "active_binding_id": str(row.get("active_binding_id") or ""),
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


def _secret_unavailable_message(hint: str) -> str:
    messages = {
        "rotate_to_store_secret": (
            "device secret is not stored for retrieval; rotate secret after setting "
            "SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY"
        ),
        "decrypt_failed": "device secret cannot be decrypted; check SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY",
        "missing_SHUXIN_DEVICE_SHARED_SECRET": "SHUXIN_DEVICE_SHARED_SECRET is not configured",
    }
    return messages.get(hint, "device secret is not available")


def _sanitize_binding_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    from shuxin.voice.mbti_reveal import sanitize_device_metadata_for_client

    return sanitize_device_metadata_for_client(metadata)


def _binding_row(row) -> dict[str, Any]:
    return {
        "binding_id": str(row["binding_id"]),
        "user_id": str(row["user_id"]),
        "device_id": str(row["device_id"]),
        "device_code": str(row["device_id"]),
        "status": str(row["status"]),
        "bound_at": _dt(row["bound_at"]),
        "unbound_at": "",
        "device": {
            "enabled": bool(row["enabled"]),
            "note": str(row["note"] or ""),
            "metadata": _sanitize_binding_metadata(_json_obj(row["metadata"])),
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


def _user_outputs_root(path: Path, user_id: str) -> Path | None:
    for parent in path.parents:
        if parent.name == user_id and parent.parent.name == "users":
            return parent
    return None


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
