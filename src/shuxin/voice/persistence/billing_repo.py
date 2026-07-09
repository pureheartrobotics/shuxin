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

def _resolve_top_up_token_by_api_key():
    from unittest.mock import Mock
    from shuxin.voice.persistence import postgres_repository
    p_func = getattr(postgres_repository, "top_up_token_by_api_key", None)
    if p_func and isinstance(p_func, Mock):
        return p_func
    global top_up_token_by_api_key
    if isinstance(top_up_token_by_api_key, Mock):
        return top_up_token_by_api_key
    return p_func or top_up_token_by_api_key

def _resolve_get_token_balance():
    from unittest.mock import Mock
    from shuxin.voice.persistence import postgres_repository
    p_func = getattr(postgres_repository, "get_token_balance", None)
    if p_func and isinstance(p_func, Mock):
        return p_func
    global get_token_balance
    if isinstance(get_token_balance, Mock):
        return get_token_balance
    return p_func or get_token_balance


COMPRESS_TARGET_RATIO = 0.8
DEVICE_CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")


class BillingRepository(BaseRepository):
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
        ratio = await self.parent.get_credit_ratio()
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
        await self.parent.audit("create_payment_plan", "payment_plan", plan_id, {"name": name})
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
        await self.parent.audit("update_payment_plan", "payment_plan", selected, payload)
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
        await self.parent.audit("disable_payment_plan", "payment_plan", selected, {})
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
        # =====================================================================
        # 【备用旧代码注释开始】 - 单设备额度查询逻辑
        # =====================================================================
        # row = await self.pool.fetchrow(
        #     """
        #     SELECT subscription_plan_id, subscription_minutes_limit, subscription_minutes_used,
        #            subscription_expires_at, fuel_minutes_balance, last_reset_month,
        #            daily_allowance_date, daily_allowance_seconds_used
        #     FROM devices
        #     WHERE device_id = $1
        #     """,
        #     device_id,
        # )
        # if row is None:
        #     return { ... }
        # ... 原单设备逻辑在此省略以备未来可能恢复使用，详细可见 Git 历史或文档 ...
        # =====================================================================
        # 【备用旧代码注释结束】
        # =====================================================================

        # 1. 查找当前设备绑定的活跃用户
        bound_row = await self.pool.fetchrow(
            """
            SELECT user_id FROM device_bindings
            WHERE device_id = $1 AND status = 'active'
            ORDER BY bound_at DESC LIMIT 1
            """,
            device_id
        )
        user_id = bound_row["user_id"] if bound_row else None

        # 2. 获取该用户名下的所有活跃设备（如果是未绑定状态，退回仅针对该单设备）
        if user_id:
            device_rows = await self.pool.fetch(
                """
                SELECT d.device_id, d.subscription_plan_id, d.subscription_minutes_limit, d.subscription_minutes_used,
                       d.subscription_expires_at, d.fuel_minutes_balance, d.last_reset_month,
                       d.daily_allowance_date, d.daily_allowance_seconds_used
                FROM devices d
                JOIN device_bindings b ON b.device_id = d.device_id AND b.status = 'active'
                WHERE b.user_id = $1
                """,
                user_id
            )
        else:
            single_row = await self.pool.fetchrow(
                """
                SELECT device_id, subscription_plan_id, subscription_minutes_limit, subscription_minutes_used,
                       subscription_expires_at, fuel_minutes_balance, last_reset_month,
                       daily_allowance_date, daily_allowance_seconds_used
                FROM devices
                WHERE device_id = $1
                """,
                device_id
            )
            device_rows = [single_row] if single_row else []

        if not device_rows:
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

        from datetime import datetime, timezone
        now_dt = datetime.now(timezone.utc)
        current_month_str = now_dt.strftime("%Y-%m")

        # 3. 统计各活跃设备的总额度
        total_sub_remaining = 0.0
        total_fuel_remaining = 0.0
        total_allowance_remaining = 0.0
        max_expires_at = None

        # 获取全局低保设置
        allowance_row = await self.pool.fetchrow(
            "SELECT daily_free_minutes, enabled FROM miniapp_allowance_settings WHERE id = 1"
        )
        daily_free_minutes = 1.5
        allowance_enabled = True
        if allowance_row is not None:
            daily_free_minutes = float(allowance_row["daily_free_minutes"])
            allowance_enabled = bool(allowance_row["enabled"])

        for row in device_rows:
            d_id = row["device_id"]
            sub_limit = float(row["subscription_minutes_limit"] or 0)
            sub_used = float(row["subscription_minutes_used"] or 0.0)
            sub_expires = row["subscription_expires_at"]
            fuel_bal = float(row["fuel_minutes_balance"] or 0.0)
            last_reset = str(row["last_reset_month"] or "").strip()
            daily_date = row["daily_allowance_date"]
            daily_seconds_used = float(row["daily_allowance_seconds_used"] or 0.0)

            # 跨月惰性重置：仅重置月度订阅已用时长，加油包永久保留
            if last_reset != current_month_str:
                sub_used = 0.0
                last_reset = current_month_str
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE devices
                        SET subscription_minutes_used = 0.0000,
                            last_reset_month = $2,
                            updated_at = now()
                        WHERE device_id = $1
                        """,
                        d_id,
                        current_month_str,
                    )

            # 计算此设备的订阅时长
            is_sub_valid = (sub_expires is not None and sub_expires > now_dt)
            if is_sub_valid:
                total_sub_remaining += max(0.0, sub_limit - sub_used)
                if max_expires_at is None or sub_expires > max_expires_at:
                    max_expires_at = sub_expires

            # 计算加油包
            total_fuel_remaining += fuel_bal

            # 计算每日低保
            allowance_remaining = 0.0
            if allowance_enabled:
                today = now_dt.date()
                if daily_date != today:
                    allowance_remaining = daily_free_minutes
                else:
                    allowance_limit_seconds = daily_free_minutes * 60.0
                    rem_seconds = max(0.0, allowance_limit_seconds - daily_seconds_used)
                    allowance_remaining = rem_seconds / 60.0
            total_allowance_remaining += allowance_remaining

        total_minutes_left = total_sub_remaining + total_fuel_remaining + total_allowance_remaining
        effective_display = round(total_minutes_left, 2)
        display_exhausted = effective_display <= 0

        # DMX 校验信息（仅 admin_detail 需要）
        api_key = ""
        credit_ratio = 1.0
        dmx_exhausted = False
        dmx_remain_yuan = None
        used_yuan = None
        dmx_unlimited = False

        if admin_detail and user_id:
            user_row = await self.pool.fetchrow(
                "SELECT llm_config FROM users WHERE user_id = $1 AND enabled = true",
                user_id
            )
            if user_row:
                api_key = str(_json_obj(user_row["llm_config"]).get("api_key") or "").strip()
                if api_key:
                    try:
                        balance = await _resolve_get_token_balance()(api_key)
                        dmx_remain_yuan = balance.get("remain_yuan")
                        used_yuan = balance.get("used_yuan")
                        dmx_exhausted = bool(balance.get("exhausted"))
                        dmx_unlimited = bool(balance.get("unlimited_quota", False))
                        credit_ratio = await self.parent.get_credit_ratio()
                    except Exception as exc:
                        logger.warning("DMX balance query failed during quota check for device %s: %s", device_id, exc)

        exhausted = display_exhausted
        result = {
            "device_id": device_id,
            "configured": True,
            "exhausted": exhausted,
            "remain_yuan": effective_display,
            "total_minutes_left": effective_display,
            "subscription_minutes_left": round(total_sub_remaining, 2),
            "fuel_minutes_left": round(total_fuel_remaining, 2),
            "daily_allowance_left": round(total_allowance_remaining, 2),
            "subscription_expires_at": _dt(max_expires_at) if max_expires_at else None,
            "unlimited_quota": dmx_unlimited,
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
            return await self.parent.get_device_quota(row["device_id"], admin_detail=admin_detail)
        
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
        quota = await self.parent.get_device_quota(device_id)
        if quota.get("exhausted"):
            raise PermissionError(QUOTA_EXHAUSTED_MESSAGE)
        remain = quota.get("remain_yuan")
        if remain is not None and float(remain) <= 0:
            raise PermissionError(QUOTA_EXHAUSTED_MESSAGE)

    async def get_user_quota_by_session(self, session_token: str) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            user_id = await self.parent._user_id_from_wechat_auth(conn, session_token=session_token)
        return await self.parent.get_user_quota_by_user_id(user_id)

    async def get_user_profile_by_session(self, session_token: str) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            user_id = await self.parent._user_id_from_wechat_auth(conn, session_token=session_token)
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
        quota = await self.parent.get_user_quota_by_user_id(user_id)
        quota_payload = {key: value for key, value in quota.items() if key != "user_id"}
        return {
            "user_id": user_id,
            "roles": {
                "factory_qa": str(meta.get("factory_role") or "").lower() == "true",
            },
            "quota": quota_payload,
        }

    async def assert_user_quota_available(self, user_id: str) -> None:
        quota = await self.parent.get_user_quota_by_user_id(user_id)
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

        credit_ratio = await self.parent.get_credit_ratio()
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
        top_up_result = await _resolve_top_up_token_by_api_key()(api_key=api_key, add_yuan=dmx_credit)
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

        await self.parent.audit(
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
        quota = await self.parent.get_user_quota_by_user_id(selected_id, admin_detail=True)
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
                user_id = await self.parent._user_id_from_wechat_auth(conn, session_token=session_token)
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
                        if sub_plan_id and sub_expires_at is not None and sub_expires_at > datetime.now(timezone.utc):
                            if sub_plan_id == plan_id:
                                raise PermissionError("您已拥有该月度套餐，在有效期内无法重复购买。")
                            
                            # 查询当前套餐与目标套餐的额度分钟数进行比较
                            curr_plan = await conn.fetchrow(
                                "SELECT duration_minutes FROM miniapp_subscription_plans WHERE plan_id = $1",
                                sub_plan_id
                            )
                            target_plan = await conn.fetchrow(
                                "SELECT duration_minutes FROM miniapp_subscription_plans WHERE plan_id = $1",
                                plan_id
                            )
                            if curr_plan and target_plan:
                                if target_plan["duration_minutes"] <= curr_plan["duration_minutes"]:
                                    raise PermissionError("您已拥有更高级别或同级别的月度套餐，在有效期内无法降级购买。")

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
        credit_ratio = await self.parent.get_credit_ratio()
        pay_yuan, display_credit, dmx_credit = compute_payment_credits(plan.amount_fen, credit_ratio)
        async with self.pool.acquire() as conn:
            user_id = await self.parent._user_id_from_wechat_auth(conn, session_token=session_token)
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
            user_id = await self.parent._user_id_from_wechat_auth(conn, session_token=session_token)
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
                    top_up_result = await _resolve_top_up_token_by_api_key()(api_key=api_key, add_yuan=dmx_credit)
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
        await self.parent.audit(
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

    async def _apply_first_activation_gift(self, conn, device_id: str) -> None:
        """从设置中查询赠送规则并为设备注入首次激活的订阅套餐。"""
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

    async def deduct_device_minutes_quota(self, device_id: str, cost_minutes: float) -> None:
        """从设备的月度订阅、加油包和低保额度中扣除会话分钟数（高精度）。"""
        if cost_minutes <= 0:
            return

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # =====================================================================
                # 【备用旧代码注释开始】 - 单设备扣减逻辑
                # =====================================================================
                # row = await conn.fetchrow(
                #     """
                #     SELECT subscription_plan_id, subscription_minutes_limit, subscription_minutes_used,
                #            subscription_expires_at, fuel_minutes_balance, last_reset_month,
                #            daily_allowance_date, daily_allowance_seconds_used
                #     FROM devices
                #     WHERE device_id = $1
                #     FOR UPDATE
                #     """,
                #     device_id,
                # )
                # ... 原单设备逻辑在此省略以备未来可能恢复使用，详细可见 Git 历史或文档 ...
                # =====================================================================
                # 【备用旧代码注释结束】
                # =====================================================================

                # 1. 查找当前设备绑定的活跃用户
                bound_row = await conn.fetchrow(
                    """
                    SELECT user_id FROM device_bindings
                    WHERE device_id = $1 AND status = 'active'
                    ORDER BY bound_at DESC LIMIT 1
                    """,
                    device_id
                )
                user_id = bound_row["user_id"] if bound_row else None

                # 2. 获取锁定该用户下所有的活跃设备行（若是未绑定状态，退回仅锁定并更新该单设备）
                if user_id:
                    device_rows = await conn.fetch(
                        """
                        SELECT d.device_id, d.subscription_plan_id, d.subscription_minutes_limit, d.subscription_minutes_used,
                               d.subscription_expires_at, d.fuel_minutes_balance, d.last_reset_month,
                               d.daily_allowance_date, d.daily_allowance_seconds_used
                        FROM devices d
                        JOIN device_bindings b ON b.device_id = d.device_id AND b.status = 'active'
                        WHERE b.user_id = $1
                        FOR UPDATE
                        """,
                        user_id
                    )
                else:
                    row = await conn.fetchrow(
                        """
                        SELECT device_id, subscription_plan_id, subscription_minutes_limit, subscription_minutes_used,
                               subscription_expires_at, fuel_minutes_balance, last_reset_month,
                               daily_allowance_date, daily_allowance_seconds_used
                        FROM devices
                        WHERE device_id = $1
                        FOR UPDATE
                        """,
                        device_id
                    )
                    device_rows = [row] if row else []

                if not device_rows:
                    return

                from datetime import datetime, timezone
                now_dt = datetime.now(timezone.utc)
                current_month_str = now_dt.strftime("%Y-%m")

                devices_state = []
                for row in device_rows:
                    d_id = row["device_id"]
                    sub_plan_id = row["subscription_plan_id"]
                    sub_limit = float(row["subscription_minutes_limit"] or 0)
                    sub_used = float(row["subscription_minutes_used"] or 0.0)
                    sub_expires = row["subscription_expires_at"]
                    fuel_bal = float(row["fuel_minutes_balance"] or 0.0)
                    last_reset = str(row["last_reset_month"] or "").strip()
                    daily_date = row["daily_allowance_date"]
                    daily_seconds_used = float(row["daily_allowance_seconds_used"] or 0.0)

                    # 跨月惰性重置：仅重置月度订阅已用时长，加油包永久保留
                    if last_reset != current_month_str:
                        sub_used = 0.0
                        last_reset = current_month_str
                        await conn.execute(
                            """
                            UPDATE devices
                            SET subscription_minutes_used = 0.0000,
                                last_reset_month = $2,
                                updated_at = now()
                            WHERE device_id = $1
                            """,
                            d_id,
                            current_month_str,
                        )

                    devices_state.append({
                        "device_id": d_id,
                        "subscription_plan_id": sub_plan_id,
                        "subscription_minutes_limit": sub_limit,
                        "subscription_minutes_used": sub_used,
                        "subscription_expires_at": sub_expires,
                        "fuel_minutes_balance": fuel_bal,
                        "last_reset_month": last_reset,
                        "daily_allowance_date": daily_date,
                        "daily_allowance_seconds_used": daily_seconds_used,
                        "dirty": False
                    })

                remaining_cost = cost_minutes

                # 3.1 第一优先级：扣减订阅时长
                for state in devices_state:
                    if remaining_cost <= 0:
                        break
                    sub_expires = state["subscription_expires_at"]
                    is_sub_valid = (sub_expires is not None and sub_expires > now_dt)
                    if is_sub_valid:
                        sub_rem = max(0.0, state["subscription_minutes_limit"] - state["subscription_minutes_used"])
                        if sub_rem > 0:
                            if sub_rem >= remaining_cost:
                                state["subscription_minutes_used"] += remaining_cost
                                remaining_cost = 0.0
                            else:
                                state["subscription_minutes_used"] = state["subscription_minutes_limit"]
                                remaining_cost -= sub_rem
                            state["dirty"] = True

                # 3.2 第二优先级：扣减加油包
                for state in devices_state:
                    if remaining_cost <= 0:
                        break
                    if state["fuel_minutes_balance"] > 0:
                        if state["fuel_minutes_balance"] >= remaining_cost:
                            state["fuel_minutes_balance"] -= remaining_cost
                            remaining_cost = 0.0
                        else:
                            remaining_cost -= state["fuel_minutes_balance"]
                            state["fuel_minutes_balance"] = 0.0
                        state["dirty"] = True

                # 3.3 第三优先级：扣减每日低保
                if remaining_cost > 0:
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
                        for state in devices_state:
                            if remaining_cost <= 0:
                                break
                            
                            daily_date = state["daily_allowance_date"]
                            daily_seconds_used = state["daily_allowance_seconds_used"]
                            
                            if daily_date != today:
                                daily_date = today
                                daily_seconds_used = 0.0

                            cost_seconds = remaining_cost * 60.0
                            allowance_limit_seconds = daily_free_minutes * 60.0
                            rem_seconds = max(0.0, allowance_limit_seconds - daily_seconds_used)

                            if rem_seconds >= cost_seconds:
                                daily_seconds_used += cost_seconds
                                remaining_cost = 0.0
                            else:
                                daily_seconds_used = allowance_limit_seconds
                                remaining_cost -= (rem_seconds / 60.0)
                            
                            state["daily_allowance_date"] = daily_date
                            state["daily_allowance_seconds_used"] = daily_seconds_used
                            state["dirty"] = True

                # 写回修改的设备额度列到数据库
                for state in devices_state:
                    if state["dirty"]:
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
                            state["device_id"],
                            state["subscription_minutes_used"],
                            state["fuel_minutes_balance"],
                            state["last_reset_month"],
                            state["daily_allowance_date"],
                            state["daily_allowance_seconds_used"],
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


    async def admin_update_allowance_settings(
        self,
        daily_free_minutes: float,
        enabled: bool,
        gift_subscription_plan_id: Optional[str],
        gift_duration_months: int,
    ) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO miniapp_allowance_settings (id, daily_free_minutes, enabled, gift_subscription_plan_id, gift_duration_months)
                VALUES (1, $1, $2, $3, $4)
                ON CONFLICT (id) DO UPDATE
                SET daily_free_minutes = EXCLUDED.daily_free_minutes,
                    enabled = EXCLUDED.enabled,
                    gift_subscription_plan_id = EXCLUDED.gift_subscription_plan_id,
                    gift_duration_months = EXCLUDED.gift_duration_months
                """,
                daily_free_minutes,
                enabled,
                gift_subscription_plan_id,
                gift_duration_months,
            )
        return {"success": True}

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


