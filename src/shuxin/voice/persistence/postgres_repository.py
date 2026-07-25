from __future__ import annotations

import logging
from typing import Any, Optional
from pathlib import Path

# Imports for test monkeypatches and references
from shuxin.voice.persistence.base_repo import (
    _verify_device_secret,
    _openid_from_wx_code,
    _hash_secret,
)
from shuxin.voice.integrations.dmx_client import (
    dmx_admin_configured,
    create_user_token,
    merge_platform_llm_defaults,
    get_token_balance,
    top_up_token_by_api_key,
)

from shuxin.voice.config.payment_config import PaymentPlan
from shuxin.voice.config.config import DeviceConfig
from shuxin.voice.persistence.users import UserSettings
from shuxin.voice.persistence.agents import AgentRecord

from shuxin.voice.persistence.device_repo import DeviceRepository
from shuxin.voice.persistence.billing_repo import BillingRepository
from shuxin.voice.persistence.mbti_repo import MbtiRepository
from shuxin.voice.persistence.factory_verify_repo import FactoryVerifyRepository
from shuxin.voice.persistence.user_repo import UserRepository
from shuxin.voice.persistence.memory_repo import MemoryRepository
from shuxin.voice.persistence.mall_repo import MallRepository
from shuxin.voice.persistence.companion_repo import CompanionRepository

class VoicePostgresRepository:
    """Voice Web 的权威数据访问层门面 (Facade)。"""

    def __init__(self, pool) -> None:
        self.pool = pool
        self.devices = DeviceRepository(pool, parent=self)
        self.billing = BillingRepository(pool, parent=self)
        self.mbti = MbtiRepository(pool, parent=self)
        self.factory = FactoryVerifyRepository(pool, parent=self)
        self.users = UserRepository(pool, parent=self)
        self.memory = MemoryRepository(pool, parent=self)
        self.mall = MallRepository(pool, parent=self)
        self.companions = CompanionRepository(pool, parent=self)

    def _clear_auth_cache(self, device_id: str | None = None) -> None:
        self.devices._clear_auth_cache(device_id)

    @property
    def _auth_cache(self) -> dict:
        return self.devices._auth_cache

    @_auth_cache.setter
    def _auth_cache(self, val: dict) -> None:
        self.devices._auth_cache = val

    def _verify_device_secret(self, row: dict[str, Any] | None, secret: str) -> bool:
        """验证设备密钥，供子仓储经由父级 Facade 调用（以兼容测试 Mock 补丁）。"""
        return _verify_device_secret(row, secret)

    # UserRepository Delegations
    async def create_wechat_session(self, *, wx_code: str) -> dict[str, Any]:
        return await self.users.create_wechat_session(wx_code=wx_code)

    async def ensure_user_dmx_llm(self, user_id: str) -> None:
        await self.users.ensure_user_dmx_llm(user_id=user_id)

    async def seed_from_yaml(
        self,
        *,
        device_config_path: str | None,
        users_config_path: str | None,
        default_device_id: str,
    ) -> None:
        await self.users.seed_from_yaml(
            device_config_path=device_config_path,
            users_config_path=users_config_path,
            default_device_id=default_device_id,
        )

    async def get_user_settings(self, user_id: str | None) -> UserSettings:
        return await self.users.get_user_settings(user_id=user_id)

    async def authenticate_user(self, user_id: str | None, token: str | None) -> UserSettings:
        return await self.users.authenticate_user(user_id=user_id, token=token)

    async def ensure_session(
        self,
        *,
        session_id: str,
        user_id: str,
        device_id: str,
        client_id: str,
    ) -> None:
        await self.users.ensure_session(
            session_id=session_id,
            user_id=user_id,
            device_id=device_id,
            client_id=client_id,
        )

    async def ensure_default_agents(self) -> None:
        await self.users.ensure_default_agents()

    async def list_agents(
        self,
        *,
        limit: int = 50,
        cursor: str = "",
        q: str = "",
    ) -> dict[str, Any]:
        return await self.users.list_agents(limit=limit, cursor=cursor, q=q)

    async def get_agent(self, agent_id: str) -> AgentRecord:
        return await self.users.get_agent(agent_id=agent_id)

    async def get_user_agent_id(self, user_id: str) -> str:
        return await self.users.get_user_agent_id(user_id=user_id)

    async def create_agent(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.users.create_agent(payload=payload)

    async def update_agent(self, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.users.update_agent(agent_id=agent_id, payload=payload)

    async def soft_delete_agent(self, agent_id: str) -> None:
        await self.users.soft_delete_agent(agent_id=agent_id)

    async def patch_user(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.users.patch_user(user_id=user_id, payload=payload)

    async def list_users(
        self,
        *,
        limit: int = 50,
        cursor: str = "",
        q: str = "",
    ) -> dict[str, Any]:
        return await self.users.list_users(limit=limit, cursor=cursor, q=q)

    async def upsert_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.users.upsert_user(payload=payload)

    async def hard_delete_user_for_test(self, user_id: str) -> None:
        await self.users.hard_delete_user_for_test(user_id=user_id)

    async def soft_delete_user(self, user_id: str) -> None:
        await self.users.soft_delete_user(user_id=user_id)

    async def audit(
        self,
        action: str,
        target_type: str,
        target_id: str,
        metadata: dict[str, Any],
    ) -> None:
        await self.users.audit(action=action, target_type=target_type, target_id=target_id, metadata=metadata)

    async def record_adapter_action(
        self,
        *,
        adapter_name: str,
        action: str,
        request_json: dict[str, Any],
        result_json: dict[str, Any] | list[Any] | None = None,
        error: str = "",
    ) -> None:
        await self.users.record_adapter_action(
            adapter_id=adapter_name,
            action=action,
            success=not bool(error),
            error_msg=error,
            metadata=request_json,
        )

    async def get_active_announcements(self) -> list[dict[str, Any]]:
        return await self.users.get_active_announcements()

    async def admin_list_announcements(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return await self.users.admin_list_announcements(limit=limit, offset=offset)

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
        return await self.users.admin_upsert_announcement(
            announcement_id=announcement_id,
            title=title,
            content=content,
            type=type,
            is_active=is_active,
            start_time=start_time,
            end_time=end_time,
        )

    async def admin_delete_announcement(self, announcement_id: int) -> dict[str, Any]:
        return await self.users.admin_delete_announcement(announcement_id=announcement_id)

    async def create_feedback(self, *, user_id: str, content: str, contact: str = "") -> dict[str, Any]:
        return await self.users.create_feedback(user_id=user_id, content=content, contact=contact)

    async def admin_list_feedbacks(
        self,
        *,
        status: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return await self.users.admin_list_feedbacks(status=status, limit=limit, offset=offset)

    async def admin_update_feedback(
        self,
        *,
        feedback_id: int,
        status: str,
        admin_notes: str = "",
    ) -> dict[str, Any]:
        return await self.users.admin_update_feedback(feedback_id=feedback_id, status=status, admin_notes=admin_notes)

    # MemoryRepository Delegations
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
        await self.memory.record_turn(
            user_settings=user_settings,
            device_id=device_id,
            client_id=client_id,
            session_id=session_id,
            turn_id=turn_id,
            user_text=user_text,
            reply_text=reply_text,
            input_audio=input_audio,
            reply_audio=reply_audio,
            timings=timings,
            warning=warning,
        )

    async def status(self, user_settings: UserSettings) -> dict[str, Any]:
        return await self.memory.status(user_settings=user_settings)

    async def export_summary(self, user_settings: UserSettings) -> dict[str, Any]:
        return await self.memory.export_summary(user_settings=user_settings)

    async def maybe_merge_rolling_summary(
        self,
        user_settings: UserSettings,
        device: DeviceConfig | None,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        return await self.memory.maybe_merge_rolling_summary(user_settings=user_settings, device=device, force=force)

    async def compress_if_needed(self, user_settings: UserSettings) -> dict[str, Any]:
        return await self.memory.compress_if_needed(user_settings=user_settings)

    async def purge_expired_audio_attachments(self, *, retention_hours: int) -> dict[str, int]:
        return await self.memory.purge_expired_audio_attachments(retention_hours=retention_hours)

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
        await self.memory._insert_attachment(
            conn=conn,
            user_id=user_id,
            device_id=device_id,
            session_id=session_id,
            turn_id=turn_id,
            kind=kind,
            path=path,
            media_type=media_type,
            compressed=compressed,
        )

    async def _attachment_total_bytes(self, conn, user_id: str) -> int:
        return await self.memory._attachment_total_bytes(conn=conn, user_id=user_id)

    async def _load_summary(self, conn, user_id: str) -> dict[str, Any]:
        return await self.memory._load_summary(conn=conn, user_id=user_id)

    async def _persist_summary(self, conn, user_id: str, summary: dict[str, Any]) -> None:
        await self.memory._persist_summary(conn=conn, user_id=user_id, summary=summary)

    async def _fetch_recent_turns(self, user_id: str, *, limit: int = 15) -> list[dict[str, Any]]:
        return await self.memory._fetch_recent_turns(user_id=user_id, limit=limit)

    async def _refresh_shared_memory(
        self,
        conn,
        user_settings: UserSettings,
        warning: str,
        *,
        user_text: str = "",
    ) -> None:
        await self.memory._refresh_shared_memory(conn=conn, user_settings=user_settings, warning=warning, user_text=user_text)

    async def _upsert_facts_from_text(self, conn, user_id: str, text: str) -> None:
        await self.memory._upsert_facts_from_text(conn=conn, user_id=user_id, text=text)

    # BillingRepository Delegations
    async def get_credit_ratio(self) -> float:
        return await self.billing.get_credit_ratio()

    async def set_credit_ratio(self, ratio: float) -> dict[str, Any]:
        return await self.billing.set_credit_ratio(ratio=ratio)

    async def get_payment_settings(self) -> dict[str, Any]:
        return await self.billing.get_payment_settings()

    async def list_payment_plans(self, *, include_disabled: bool = False) -> list[PaymentPlan]:
        return await self.billing.list_payment_plans(include_disabled=include_disabled)

    async def list_miniapp_payment_plans(self) -> list[dict[str, Any]]:
        return await self.billing.list_miniapp_payment_plans()

    async def get_payment_plan(self, plan_id: str) -> PaymentPlan:
        return await self.billing.get_payment_plan(plan_id=plan_id)

    async def create_payment_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.billing.create_payment_plan(payload=payload)

    async def update_payment_plan(self, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.billing.update_payment_plan(plan_id=plan_id, payload=payload)

    async def soft_delete_payment_plan(self, plan_id: str) -> dict[str, Any]:
        return await self.billing.soft_delete_payment_plan(plan_id=plan_id)

    async def get_device_quota(
        self, device_id: str, *, admin_detail: bool = False
    ) -> dict[str, Any]:
        return await self.billing.get_device_quota(device_id=device_id, admin_detail=admin_detail)

    async def get_user_quota_by_user_id(
        self, user_id: str, *, admin_detail: bool = False
    ) -> dict[str, Any]:
        return await self.billing.get_user_quota_by_user_id(user_id=user_id, admin_detail=admin_detail)

    async def assert_device_quota_available(self, device_id: str) -> None:
        await self.billing.assert_device_quota_available(device_id=device_id)

    async def get_user_quota_by_session(self, session_token: str) -> dict[str, Any]:
        return await self.billing.get_user_quota_by_session(session_token=session_token)

    async def get_user_profile_by_session(self, session_token: str) -> dict[str, Any]:
        return await self.billing.get_user_profile_by_session(session_token=session_token)

    async def update_user_profile_by_session(
        self,
        session_token: str,
        *,
        nickname: Optional[str] = None,
        avatar_key: Optional[str] = None,
    ) -> dict[str, Any]:
        return await self.billing.update_user_profile_by_session(
            session_token,
            nickname=nickname,
            avatar_key=avatar_key,
        )

    async def clear_user_avatar_by_session(self, session_token: str) -> dict[str, Any]:
        return await self.billing.clear_user_avatar_by_session(session_token)

    async def assert_user_quota_available(self, user_id: str) -> None:
        await self.billing.assert_user_quota_available(user_id=user_id)

    async def top_up_user_dmx_quota(
        self,
        user_id: str,
        *,
        add_yuan: float,
        note: str = "",
    ) -> dict[str, Any]:
        return await self.billing.top_up_user_dmx_quota(user_id=user_id, add_yuan=add_yuan, note=note)

    async def create_payment_order(
        self,
        *,
        session_token: str,
        plan_id: str,
        device_id: str | None = None,
    ) -> dict[str, Any]:
        return await self.billing.create_payment_order(session_token=session_token, plan_id=plan_id, device_id=device_id)

    async def attach_prepay_id(self, *, out_trade_no: str, prepay_id: str) -> None:
        await self.billing.attach_prepay_id(out_trade_no=out_trade_no, prepay_id=prepay_id)

    async def list_payment_orders_by_session(
        self,
        session_token: str,
        *,
        limit: int = 20,
    ) -> dict[str, Any]:
        return await self.billing.list_payment_orders_by_session(session_token=session_token, limit=limit)

    async def fulfill_payment_order(
        self,
        *,
        out_trade_no: str,
        wx_transaction_id: str,
        notify_payload: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.billing.fulfill_payment_order(out_trade_no=out_trade_no, wx_transaction_id=wx_transaction_id, notify_payload=notify_payload)

    async def admin_list_subscription_plans(self) -> list[dict[str, Any]]:
        return await self.billing.admin_list_subscription_plans()

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
        return await self.billing.admin_upsert_subscription_plan(
            plan_id=plan_id,
            name=name,
            amount_fen=amount_fen,
            duration_minutes=duration_minutes,
            description=description,
            sort_order=sort_order,
            enabled=enabled,
        )

    async def admin_delete_subscription_plan(self, plan_id: str) -> dict[str, Any]:
        return await self.billing.admin_delete_subscription_plan(plan_id=plan_id)

    async def admin_list_fuel_packages(self) -> list[dict[str, Any]]:
        return await self.billing.admin_list_fuel_packages()

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
        return await self.billing.admin_upsert_fuel_package(
            package_id=package_id,
            name=name,
            amount_fen=amount_fen,
            duration_minutes=duration_minutes,
            description=description,
            sort_order=sort_order,
            enabled=enabled,
        )

    async def admin_delete_fuel_package(self, package_id: str) -> dict[str, Any]:
        return await self.billing.admin_delete_fuel_package(package_id=package_id)

    async def deduct_device_minutes_quota(self, device_id: str, cost_minutes: float) -> None:
        await self.billing.deduct_device_minutes_quota(device_id=device_id, cost_minutes=cost_minutes)

    async def _apply_first_activation_gift(self, conn, device_id: str) -> None:
        await self.billing._apply_first_activation_gift(conn=conn, device_id=device_id)

    async def _get_display_balance(self, metadata: dict[str, Any]) -> float:
        return await self.billing._get_display_balance(metadata=metadata)

    async def _persist_display_balance(self, conn, user_id: str, metadata: dict[str, Any], amount: float) -> None:
        await self.billing._persist_display_balance(conn=conn, user_id=user_id, metadata=metadata, amount=amount)

    async def _add_display_balance(self, conn, user_id: str, *, delta: float, metadata: dict[str, Any]) -> float:
        return await self.billing._add_display_balance(conn=conn, user_id=user_id, delta=delta, metadata=metadata)

    async def _extend_subscription(self, conn, *, user_id: str, duration_days: int) -> None:
        await self.billing._extend_subscription(conn=conn, user_id=user_id, duration_days=duration_days)

    async def get_pricing_by_type(self, service_type: str) -> dict[str, float]:
        return await self.billing.get_pricing_by_type(service_type=service_type)

    async def insert_expenditure(
        self,
        *,
        user_id: str,
        service_type: str,
        model_name: str,
        usage_amount: float,
        cost_yuan: float,
    ) -> None:
        await self.billing.insert_expenditure(
            user_id=user_id,
            service_type=service_type,
            model_name=model_name,
            usage_amount=usage_amount,
            cost_yuan=cost_yuan,
        )

    async def get_monthly_expenditure_summary(self, month_str: str) -> dict[str, Any]:
        return await self.billing.get_monthly_expenditure_summary(month_str=month_str)

    async def list_expenditures(
        self,
        *,
        month_str: str,
        user_id: str = "",
        limit: int = 50,
        cursor: str = "",
    ) -> dict[str, Any]:
        return await self.billing.list_expenditures(
            month_str=month_str,
            user_id=user_id,
            limit=limit,
            cursor=cursor,
        )

    async def delete_expenditure(self, expenditure_id: str) -> bool:
        return await self.billing.delete_expenditure(expenditure_id=expenditure_id)

    async def delete_monthly_expenditures(self, month_str: str) -> int:
        return await self.billing.delete_monthly_expenditures(month_str=month_str)

    async def get_all_pricing(self) -> dict[str, Any]:
        return await self.billing.get_all_pricing()

    async def update_pricing(self, pricing_type: str, pricing_dict: dict[str, float]) -> None:
        await self.billing.update_pricing(pricing_type=pricing_type, pricing_dict=pricing_dict)

    # DeviceRepository Delegations
    async def provision_device(self, device_code: str) -> dict[str, Any]:
        return await self.devices.provision_device(device_code=device_code)

    async def provision_devices_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.devices.provision_devices_batch(payload=payload)

    async def next_device_sequence(self, device_prefix: str) -> dict[str, Any]:
        return await self.devices.next_device_sequence(device_prefix=device_prefix)

    async def bind_device(
        self,
        *,
        wx_code: str = "",
        session_token: str = "",
        claim_code: str = "",
        device_code: str = "",
    ) -> dict[str, Any]:
        return await self.devices.bind_device(wx_code=wx_code, session_token=session_token, claim_code=claim_code, device_code=device_code)

    async def authenticate_device(
        self,
        device_code: str | None,
        device_secret: str | None,
    ) -> UserSettings:
        return await self.devices.authenticate_device(device_code, device_secret)

    async def authenticate_device_for_factory(
        self,
        device_code: str | None,
        device_secret: str | None,
    ) -> UserSettings:
        return await self.devices.authenticate_device_for_factory(device_code, device_secret)

    async def unbind_device(self, *, user_id: str, device_code: str) -> dict[str, Any]:
        return await self.devices.unbind_device(user_id=user_id, device_code=device_code)

    async def list_my_devices(self, *, wx_code: str, session_token: str = "") -> dict[str, Any]:
        return await self.devices.list_my_devices(wx_code=wx_code, session_token=session_token)

    async def unbind_device_by_wx_code(
        self, *, wx_code: str, device_code: str
    ) -> dict[str, Any]:
        return await self.devices.unbind_device_by_wx_code(wx_code=wx_code, device_code=device_code)

    async def unbind_device_by_session(
        self, *, session_token: str, device_code: str
    ) -> dict[str, Any]:
        return await self.devices.unbind_device_by_session(session_token=session_token, device_code=device_code)

    async def list_bindings(
        self, *, limit: int = 50, cursor: str = "", q: str = ""
    ) -> dict[str, Any]:
        return await self.devices.list_bindings(limit=limit, cursor=cursor, q=q)

    async def admin_bind_device(self, *, user_id: str, device_id: str) -> dict[str, Any]:
        return await self.devices.admin_bind_device(user_id=user_id, device_id=device_id)

    async def admin_unbind_device(self, *, binding_id: str) -> dict[str, Any]:
        return await self.devices.admin_unbind_device(binding_id=binding_id)

    async def get_device(self, device_id: str | None) -> DeviceConfig:
        return await self.devices.get_device(device_id=device_id)

    async def touch_device_status(
        self,
        device_id: str,
        *,
        online: bool,
        session_id: str = "",
        error: str = "",
    ) -> None:
        await self.devices.touch_device_status(device_id=device_id, online=online, session_id=session_id, error=error)

    async def reveal_device_secret(self, device_id: str) -> dict[str, Any]:
        return await self.devices.reveal_device_secret(device_id=device_id)

    async def list_devices(
        self, *, limit: int = 50, cursor: str = "", q: str = ""
    ) -> dict[str, Any]:
        return await self.devices.list_devices(limit=limit, cursor=cursor, q=q)

    async def update_device_label(self, device_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.devices.update_device_label(device_id=device_id, payload=payload)

    async def reset_claim_code(self, device_id: str) -> dict[str, Any]:
        return await self.devices.reset_claim_code(device_id=device_id)

    async def rotate_device_secret(self, device_id: str) -> dict[str, Any]:
        return await self.devices.rotate_device_secret(device_id=device_id)

    async def upsert_device(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.devices.upsert_device(payload=payload)

    async def soft_delete_device(self, device_id: str) -> None:
        await self.devices.soft_delete_device(device_id=device_id)

    async def list_voice_demo_targets(self) -> dict[str, Any]:
        return await self.devices.list_voice_demo_targets()

    async def apply_default_stt_to_all_devices(self) -> dict[str, Any]:
        return await self.devices.apply_default_stt_to_all_devices()

    async def apply_default_tts_to_all_devices(self) -> dict[str, Any]:
        return await self.devices.apply_default_tts_to_all_devices()

    async def _bind_device_for_user(
        self,
        conn,
        *,
        user_id: str,
        device_id: str,
        event_type: str,
    ) -> dict[str, Any]:
        return await self.devices._bind_device_for_user(conn=conn, user_id=user_id, device_id=device_id, event_type=event_type)

    async def _insert_provisioned_device(
        self,
        conn,
        *,
        device_id: str,
        device_secret: str,
        claim_code: str,
        note: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        return await self.devices._insert_provisioned_device(
            conn=conn,
            device_id=device_id,
            device_secret=device_secret,
            claim_code=claim_code,
            note=note,
            metadata=metadata,
        )

    async def _find_active_claim(self, conn, claim_code: str):
        return await self.devices._find_active_claim(conn=conn, claim_code=claim_code)

    async def _find_claim_status(self, conn, claim_code: str) -> str:
        return await self.devices._find_claim_status(conn=conn, claim_code=claim_code)

    async def _user_id_from_wechat_auth(self, conn, *, session_token: str = "", wx_code: str = "") -> str:
        return await self.devices._user_id_from_wechat_auth(conn=conn, session_token=session_token, wx_code=wx_code)

    async def _unbind_active_device(self, user_id: str, device_id: str, *, event_type: str) -> dict[str, Any]:
        return await self.devices._unbind_active_device(user_id=user_id, device_id=device_id, event_type=event_type)

    async def _restore_latest_claim_code(self, conn, device_id: str) -> None:
        await self.devices._restore_latest_claim_code(conn=conn, device_id=device_id)

    async def _record_auth_failure(self, device_id: str) -> None:
        await self.devices._record_auth_failure(device_id=device_id)

    async def _record_binding_event(
        self,
        conn,
        *,
        event_type: str,
        user_id: str | None = None,
        device_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.devices._record_binding_event(conn=conn, event_type=event_type, user_id=user_id, device_id=device_id, metadata=metadata)

    # MbtiRepository Delegations
    async def _attach_mbti_reveal_on_bind(
        self,
        conn,
        device_id: str,
    ) -> dict[str, Any] | None:
        return await self.mbti._attach_mbti_reveal_on_bind(conn=conn, device_id=device_id)

    async def _try_reveal_and_lock_conn(
        self,
        conn,
        device_id: str,
        revealed_by: str,
    ) -> dict[str, Any] | None:
        return await self.mbti._try_reveal_and_lock_conn(conn=conn, device_id=device_id, revealed_by=revealed_by)

    async def try_reveal_and_lock(self, device_id: str, revealed_by: str) -> dict[str, Any] | None:
        return await self.mbti.try_reveal_and_lock(device_id=device_id, revealed_by=revealed_by)

    async def mark_device_intro_played(self, device_id: str) -> dict[str, Any]:
        return await self.mbti.mark_device_intro_played(device_id=device_id)

    async def update_device_mbti(self, device_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.mbti.update_device_mbti(device_id=device_id, payload=payload)

    async def mark_mbti_locked(self, device_id: str) -> dict[str, Any]:
        return await self.mbti.mark_mbti_locked(device_id=device_id)

    # FactoryVerifyRepository Delegations
    async def factory_verify_lookup(self, claim_code: str) -> dict[str, Any]:
        return await self.factory.factory_verify_lookup(claim_code=claim_code)

    async def factory_verify_user_has_role(self, session_token: str) -> str:
        return await self.factory.factory_verify_user_has_role(session_token=session_token)

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
        await self.factory.factory_verify_log(verify_id=verify_id, claim_code=claim_code, device_id=device_id, operator_user=operator_user, result=result, fail_reason=fail_reason, meta=meta)

    async def factory_verify_logs_list(
        self,
        *,
        operator_user: str = "",
        device_id: str = "",
        limit: int = 50,
        retention_days: int = 0,
    ) -> list[dict[str, Any]]:
        return await self.factory.factory_verify_logs_list(operator_user=operator_user, device_id=device_id, limit=limit, retention_days=retention_days)

    async def purge_expired_factory_verify_logs(self, *, retention_days: int) -> dict[str, int]:
        return await self.factory.purge_expired_factory_verify_logs(retention_days=retention_days)

    async def admin_update_allowance_settings(
        self,
        daily_free_minutes: float,
        enabled: bool,
        gift_subscription_plan_id: Optional[str] = None,
        gift_duration_months: int = 0,
    ) -> dict[str, Any]:
        return await self.billing.admin_update_allowance_settings(
            daily_free_minutes=daily_free_minutes,
            enabled=enabled,
            gift_subscription_plan_id=gift_subscription_plan_id,
            gift_duration_months=gift_duration_months,
        )

    async def admin_get_allowance_settings(self) -> dict[str, Any]:
        return await self.billing.admin_get_allowance_settings()
