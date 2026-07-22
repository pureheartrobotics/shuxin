"""Software companions + gacha persistence (investor demo line)."""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from typing import Any, Optional

from shuxin.core.identity import IdentityEngine, MBTI_DESCRIPTIONS
from shuxin.voice.billing.gacha import merge_gacha_settings, weighted_pick_mbti
from shuxin.voice.billing.text_billing import merge_text_billing_settings
from shuxin.voice.config.mbti_reveal import mbti_display_name
from shuxin.voice.config.config import default_device_tts_config, default_tencent_stt_config
from shuxin.voice.persistence.base_repo import BaseRepository, _hash_secret
from shuxin.voice.persistence.device_secret_crypto import (
    encrypt_device_secret,
    require_device_secret_encryption,
)

logger = logging.getLogger("shuxin.voice.companions")

GACHA_SETTING_KEY = "investor.gacha"
TEXT_BILLING_SETTING_KEY = "investor.text_billing"
GACHA_PLAN_ID = "gacha_draw"
SOFT_DEVICE_PREFIX = "soft_"


def _json_obj(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            data = json.loads(value)
            return dict(data) if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


class CompanionRepository(BaseRepository):
    async def _get_setting(self, key: str) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM platform_settings WHERE key = $1",
                key,
            )
        if not row:
            return {}
        return _json_obj(row["value"])

    async def _set_setting(self, key: str, value: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(value, ensure_ascii=False)
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO platform_settings (key, value, updated_at)
                VALUES ($1, $2::jsonb, now())
                ON CONFLICT (key) DO UPDATE
                SET value = excluded.value, updated_at = now()
                """,
                key,
                payload,
            )
        return value

    async def get_gacha_settings(self) -> dict[str, Any]:
        return merge_gacha_settings(await self._get_setting(GACHA_SETTING_KEY))

    async def set_gacha_settings(self, value: dict[str, Any]) -> dict[str, Any]:
        merged = merge_gacha_settings(value)
        await self._set_setting(GACHA_SETTING_KEY, merged)
        return merged

    async def get_text_billing_settings(self) -> dict[str, Any]:
        return merge_text_billing_settings(await self._get_setting(TEXT_BILLING_SETTING_KEY))

    async def set_text_billing_settings(self, value: dict[str, Any]) -> dict[str, Any]:
        merged = merge_text_billing_settings(value)
        await self._set_setting(TEXT_BILLING_SETTING_KEY, merged)
        return merged

    async def _user_id_from_session(self, session_token: str) -> str:
        selected = str(session_token or "").strip()
        if not selected:
            raise PermissionError("session_token is required")
        token_hash = _hash_secret(selected)
        async with self.pool.acquire() as conn:
            user_id = await conn.fetchval(
                """
                SELECT user_id FROM wechat_sessions
                WHERE session_token_hash = $1 AND expires_at > now()
                """,
                token_hash,
            )
        if not user_id:
            raise PermissionError("session_token is invalid or expired")
        return str(user_id)

    async def _get_user_metadata(self, conn, user_id: str) -> dict[str, Any]:
        row = await conn.fetchrow(
            "SELECT metadata FROM users WHERE user_id = $1 AND deleted_at IS NULL",
            user_id,
        )
        if not row:
            raise PermissionError("user not found")
        return _json_obj(row["metadata"])

    async def _set_user_metadata(self, conn, user_id: str, metadata: dict[str, Any]) -> None:
        await conn.execute(
            """
            UPDATE users
            SET metadata = $2::jsonb, updated_at = now()
            WHERE user_id = $1 AND deleted_at IS NULL
            """,
            user_id,
            json.dumps(metadata, ensure_ascii=False),
        )

    def _default_display_name(self, mbti: str) -> str:
        engine = IdentityEngine(mbti_type=mbti)
        tagline = engine.get_description() or MBTI_DESCRIPTIONS.get(mbti, mbti)
        return mbti_display_name(tagline, mbti)

    async def get_gacha_config_for_user(self, *, session_token: str) -> dict[str, Any]:
        user_id = await self._user_id_from_session(session_token)
        settings = await self.get_gacha_settings()
        async with self.pool.acquire() as conn:
            meta = await self._get_user_metadata(conn, user_id)
        free_default = int(settings.get("free_draws_per_user") or 3)
        remaining = meta.get("free_gacha_remaining")
        if remaining is None:
            remaining = free_default
        return {
            "paid_draw_price_yuan": float(settings["paid_draw_price_yuan"]),
            "free_draws_per_user": free_default,
            "free_gacha_remaining": int(remaining),
            "weights": dict(settings.get("weights") or {}),
        }

    async def list_companions(self, *, session_token: str) -> dict[str, Any]:
        user_id = await self._user_id_from_session(session_token)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT companion_id, mbti, display_name, source, created_at
                FROM user_companions
                WHERE user_id = $1
                ORDER BY created_at DESC
                """,
                user_id,
            )
        items = []
        for row in rows:
            items.append(
                {
                    "companion_id": row["companion_id"],
                    "mbti": row["mbti"],
                    "display_name": row["display_name"],
                    "source": row["source"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                }
            )
        return {"items": items}

    async def rename_companion(
        self, *, session_token: str, companion_id: str, display_name: str
    ) -> dict[str, Any]:
        user_id = await self._user_id_from_session(session_token)
        name = str(display_name or "").strip()
        if not name or len(name) > 32:
            raise ValueError("display_name must be 1..32 chars")
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE user_companions
                SET display_name = $3
                WHERE companion_id = $1 AND user_id = $2
                RETURNING companion_id, mbti, display_name, source, created_at
                """,
                companion_id,
                user_id,
                name,
            )
        if not row:
            raise PermissionError("companion not found")
        return {
            "companion_id": row["companion_id"],
            "mbti": row["mbti"],
            "display_name": row["display_name"],
            "source": row["source"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }

    async def get_companion_for_user(self, *, user_id: str, companion_id: str) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT companion_id, user_id, mbti, display_name, source
                FROM user_companions
                WHERE companion_id = $1 AND user_id = $2
                """,
                companion_id,
                user_id,
            )
        if not row:
            raise PermissionError("companion not found")
        return dict(row)

    async def ensure_soft_device(self, *, user_id: str) -> dict[str, Any]:
        """One soft device per user; returns plaintext secret only when newly created."""
        soft_id = f"{SOFT_DEVICE_PREFIX}{user_id}"[:96]
        async with self.pool.acquire() as conn:
            existing = await conn.fetchrow(
                """
                SELECT device_id, metadata
                FROM devices
                WHERE device_id = $1 AND deleted_at IS NULL
                """,
                soft_id,
            )
            if existing:
                return {"device_id": soft_id, "created": False, "device_secret": None}

            require_device_secret_encryption()
            device_secret = secrets.token_urlsafe(32)
            secret_hash = _hash_secret(device_secret)
            encrypted = encrypt_device_secret(device_secret)
            metadata = {
                "kind": "soft",
                "soft_for_user": user_id,
                "mbti_status": "locked",
            }
            stt_config = json.dumps(default_tencent_stt_config(), ensure_ascii=False)
            tts_config = json.dumps(default_device_tts_config(), ensure_ascii=False)
            await conn.execute(
                """
                INSERT INTO devices (
                    device_id, auth_mode, device_secret_hash, device_secret_encrypted,
                    stt_config, tts_config,
                    status, enabled, note, metadata, bound_user_id, updated_at
                )
                VALUES (
                    $1, 'per_device_secret', $2, $3, $4::jsonb, $5::jsonb,
                    'bound', true, $6, $7::jsonb, $8, now()
                )
                """,
                soft_id,
                secret_hash,
                encrypted,
                stt_config,
                tts_config,
                "investor soft device",
                json.dumps(metadata, ensure_ascii=False),
                user_id,
            )
            await conn.execute(
                "INSERT INTO device_status (device_id) VALUES ($1) ON CONFLICT (device_id) DO NOTHING",
                soft_id,
            )
            return {"device_id": soft_id, "created": True, "device_secret": device_secret}

    async def issue_soft_credentials(self, *, session_token: str) -> dict[str, Any]:
        """Return soft device_id + secret (rotate if missing plaintext path)."""
        user_id = await self._user_id_from_session(session_token)
        require_device_secret_encryption()
        soft_id = f"{SOFT_DEVICE_PREFIX}{user_id}"[:96]
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT device_id, device_secret_encrypted, metadata
                FROM devices
                WHERE device_id = $1 AND deleted_at IS NULL
                """,
                soft_id,
            )
            if not row:
                created = await self.ensure_soft_device(user_id=user_id)
                return {
                    "device_id": created["device_id"],
                    "device_secret": created["device_secret"],
                    "auth_mode": "per_device_secret",
                }
            # Rotate secret so client always gets a usable plaintext
            device_secret = secrets.token_urlsafe(32)
            secret_hash = _hash_secret(device_secret)
            encrypted = encrypt_device_secret(device_secret)
            meta = _json_obj(row["metadata"])
            meta["kind"] = "soft"
            meta["soft_for_user"] = user_id
            await conn.execute(
                """
                UPDATE devices
                SET device_secret_hash = $2,
                    device_secret_encrypted = $3,
                    metadata = $4::jsonb,
                    bound_user_id = $5,
                    updated_at = now()
                WHERE device_id = $1
                """,
                soft_id,
                secret_hash,
                encrypted,
                json.dumps(meta, ensure_ascii=False),
                user_id,
            )
        if self.parent is not None:
            try:
                self.parent._clear_auth_cache(soft_id)
            except Exception:
                pass
        return {
            "device_id": soft_id,
            "device_secret": device_secret,
            "auth_mode": "per_device_secret",
        }

    async def draw_companion(
        self,
        *,
        session_token: str,
        payment_id: str | None = None,
    ) -> dict[str, Any]:
        user_id = await self._user_id_from_session(session_token)
        settings = await self.get_gacha_settings()
        free_default = int(settings.get("free_draws_per_user") or 3)
        pay_id = str(payment_id or "").strip()

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                meta = await self._get_user_metadata(conn, user_id)
                remaining = meta.get("free_gacha_remaining")
                if remaining is None:
                    remaining = free_default
                remaining = int(remaining)

                source = "free_gacha"
                if pay_id:
                    source = "paid_gacha"
                    order = await conn.fetchrow(
                        """
                        SELECT order_id, user_id, plan_id, status
                        FROM payment_orders
                        WHERE order_id = $1
                        FOR UPDATE
                        """,
                        pay_id,
                    )
                    if not order or str(order["user_id"]) != user_id:
                        raise PermissionError("payment not found")
                    if str(order["plan_id"]) != GACHA_PLAN_ID:
                        raise ValueError("payment is not a gacha order")
                    if str(order["status"]) != "paid":
                        raise ValueError("payment not paid")
                    used = await conn.fetchval(
                        """
                        SELECT 1 FROM user_companions WHERE payment_id = $1
                        """,
                        pay_id,
                    )
                    if used:
                        raise ValueError("payment already redeemed")
                else:
                    if remaining <= 0:
                        raise ValueError("no free draws remaining")
                    remaining -= 1
                    meta["free_gacha_remaining"] = remaining
                    await self._set_user_metadata(conn, user_id, meta)

                mbti = weighted_pick_mbti(settings)
                companion_id = f"cmp_{uuid.uuid4().hex[:16]}"
                display_name = self._default_display_name(mbti)
                await conn.execute(
                    """
                    INSERT INTO user_companions (
                        companion_id, user_id, mbti, display_name, source, payment_id
                    )
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    companion_id,
                    user_id,
                    mbti,
                    display_name,
                    source,
                    pay_id if source == "paid_gacha" else "",
                )

        await self.ensure_soft_device(user_id=user_id)
        return {
            "companion": {
                "companion_id": companion_id,
                "mbti": mbti,
                "display_name": display_name,
                "source": source,
            },
            "free_gacha_remaining": remaining if source == "free_gacha" else (
                int((await self.get_gacha_config_for_user(session_token=session_token))[
                    "free_gacha_remaining"
                ])
            ),
            "letters": list(mbti),
        }

    async def create_gacha_payment_order(self, *, session_token: str) -> dict[str, Any]:
        user_id = await self._user_id_from_session(session_token)
        settings = await self.get_gacha_settings()
        price_yuan = float(settings["paid_draw_price_yuan"])
        amount_fen = max(1, int(round(price_yuan * 100)))
        order_id = f"gch_{uuid.uuid4().hex[:18]}"
        out_trade_no = f"gacha{uuid.uuid4().hex[:24]}"
        import os

        mock = (os.environ.get("SHUXIN_WECHAT_MOCK") or "").strip() in ("1", "true", "yes")
        status = "paid" if mock else "pending"
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO payment_orders (
                    order_id, user_id, out_trade_no, plan_id, plan_name,
                    amount_fen, add_yuan, pay_yuan, duration_days, status, paid_at
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $7, 0, $8,
                    CASE WHEN $8 = 'paid' THEN now() ELSE NULL END
                )
                """,
                order_id,
                user_id,
                out_trade_no,
                GACHA_PLAN_ID,
                "抽卡一次",
                amount_fen,
                price_yuan,
                status,
            )
        return {
            "order_id": order_id,
            "out_trade_no": out_trade_no,
            "amount_fen": amount_fen,
            "amount_yuan": price_yuan,
            "status": status,
            "mock_paid": mock,
        }

    async def record_text_turn(
        self,
        *,
        user_id: str,
        companion_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        cache_tokens: int,
        cost_minutes: float,
    ) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO companion_text_turns (
                    user_id, companion_id, prompt_tokens, completion_tokens,
                    cache_tokens, cost_minutes
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                user_id,
                companion_id,
                int(prompt_tokens),
                int(completion_tokens),
                int(cache_tokens),
                float(cost_minutes),
            )

    async def investor_metrics(self) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            registered = int(
                await conn.fetchval(
                    "SELECT COUNT(*) FROM users WHERE deleted_at IS NULL"
                )
                or 0
            )
            companions = int(
                await conn.fetchval("SELECT COUNT(*) FROM user_companions") or 0
            )
            free_draws = int(
                await conn.fetchval(
                    "SELECT COUNT(*) FROM user_companions WHERE source = 'free_gacha'"
                )
                or 0
            )
            paid_draws = int(
                await conn.fetchval(
                    "SELECT COUNT(*) FROM user_companions WHERE source = 'paid_gacha'"
                )
                or 0
            )
            paid_users = int(
                await conn.fetchval(
                    """
                    SELECT COUNT(DISTINCT user_id)
                    FROM user_companions WHERE source = 'paid_gacha'
                    """
                )
                or 0
            )
            exhausted = int(
                await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM users
                    WHERE deleted_at IS NULL
                      AND COALESCE((metadata->>'free_gacha_remaining')::int, 3) <= 0
                    """
                )
                or 0
            )
            text_turns = int(
                await conn.fetchval("SELECT COUNT(*) FROM companion_text_turns") or 0
            )
            voice_turns = 0
            try:
                voice_turns = int(
                    await conn.fetchval(
                        """
                        SELECT COUNT(*) FROM user_expenditures
                        WHERE created_at > now() - interval '365 days'
                        """
                    )
                    or 0
                )
            except Exception:
                voice_turns = 0
        conversion = (paid_users / exhausted) if exhausted > 0 else 0.0
        return {
            "registered_users": registered,
            "companions_total": companions,
            "free_draws": free_draws,
            "paid_draws": paid_draws,
            "paid_draw_users": paid_users,
            "free_exhausted_users": exhausted,
            "paid_draw_conversion": round(conversion, 4),
            "text_turns": text_turns,
            "voice_turns_proxy": voice_turns,
        }
