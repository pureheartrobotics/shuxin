from __future__ import annotations

import uuid
import logging
from pathlib import Path
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, FileResponse

from shuxin.voice.persistence.agents import DEFAULT_AGENT_ID
from shuxin.core.identity import load_mbti_profiles
from shuxin.voice.integrations.dmx_client import default_platform_llm_config
from shuxin.voice.config.tts_config import create_tts_provider_from_agent
from shuxin.voice.api.routers.deps import get_repo, require_admin

logger = logging.getLogger("shuxin.voice.api.routers.admin")

# Router level dependencies: require_admin applied to ALL routes automatically!
router = APIRouter(
    prefix="/admin/api",
    dependencies=[Depends(require_admin)],
    tags=["Admin"],
)


@router.get("/devices")
async def admin_list_devices(limit: int = 50, cursor: str = "", q: str = "", repo=Depends(get_repo)):
    return JSONResponse(await repo.list_devices(limit=limit, cursor=cursor, q=q))


@router.post("/devices")
async def admin_upsert_device(request: Request, repo=Depends(get_repo)):
    payload = await request.json()
    return JSONResponse(await repo.upsert_device(payload))


@router.post("/devices/apply-stt-defaults")
async def admin_apply_stt_defaults(repo=Depends(get_repo)):
    return JSONResponse(await repo.apply_default_stt_to_all_devices())


@router.post("/devices/apply-tts-defaults")
async def admin_apply_tts_defaults(repo=Depends(get_repo)):
    return JSONResponse(await repo.apply_default_tts_to_all_devices())


@router.get("/agents")
async def admin_list_agents(limit: int = 50, cursor: str = "", q: str = "", repo=Depends(get_repo)):
    return JSONResponse(await repo.list_agents(limit=limit, cursor=cursor, q=q))


@router.post("/agents")
async def admin_create_agent(request: Request, repo=Depends(get_repo)):
    payload = await request.json()
    return JSONResponse(await repo.create_agent(payload))


@router.get("/agents/{agent_id}")
async def admin_get_agent(agent_id: str, repo=Depends(get_repo)):
    try:
        record = await repo.get_agent(agent_id)
        return JSONResponse(record.to_admin_dict())
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)


@router.patch("/agents/{agent_id}")
async def admin_update_agent(agent_id: str, request: Request, repo=Depends(get_repo)):
    payload = await request.json()
    return JSONResponse(await repo.update_agent(agent_id, payload))


@router.delete("/agents/{agent_id}")
async def admin_delete_agent(agent_id: str, repo=Depends(get_repo)):
    await repo.soft_delete_agent(agent_id)
    return JSONResponse({"ok": True})


@router.patch("/users/{user_id}")
async def admin_patch_user(user_id: str, request: Request, repo=Depends(get_repo)):
    payload = await request.json()
    return JSONResponse(await repo.patch_user(user_id, payload))


@router.patch("/users/{user_id}/voice-preferences")
async def admin_user_voice_preferences(user_id: str):
    del user_id
    return JSONResponse(
        {"error": "voice-preferences API reserved for future user-facing customization"},
        status_code=501,
    )


@router.post("/tts/preview")
async def admin_tts_preview(request: Request, repo=Depends(get_repo)):
    payload = await request.json()
    agent_id = str(payload.get("agent_id") or DEFAULT_AGENT_ID)
    text = str(payload.get("text") or "你好，这是音色试听。")
    agent_record = await repo.get_agent(agent_id)
    
    out_dir = getattr(request.app.state, "out_dir", Path("outputs/web"))
    preview_dir = out_dir / "admin-preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.mp3"
    path = preview_dir / filename
    
    provider = create_tts_provider_from_agent(agent_record, output_dir=str(preview_dir))
    await provider.synthesize(text, path)
    return JSONResponse(
        {
            "agent_id": agent_id,
            "text": text,
            "audio_path": str(path),
            "audio_url": f"/admin/api/tts/preview/files/{filename}",
        }
    )


@router.get("/tts/preview/files/{filename}")
async def admin_tts_preview_file(request: Request, filename: str):
    safe_name = Path(filename).name
    out_dir = getattr(request.app.state, "out_dir", Path("outputs/web"))
    path = out_dir / "admin-preview" / safe_name
    if not path.is_file():
        return JSONResponse({"error": "preview file not found"}, status_code=404)
    return FileResponse(path, media_type="audio/mpeg", filename=safe_name)


@router.patch("/devices/{device_id}")
async def admin_update_device_label(device_id: str, request: Request, repo=Depends(get_repo)):
    payload = await request.json()
    return JSONResponse(await repo.update_device_label(device_id, payload))


@router.patch("/devices/{device_id}/mbti")
async def admin_update_device_mbti(device_id: str, request: Request, repo=Depends(get_repo)):
    payload = await request.json()
    return JSONResponse(await repo.update_device_mbti(device_id, payload))


@router.get("/mbti/types")
async def admin_list_mbti_types():
    profiles = load_mbti_profiles()
    items = [
        {"type": mbti, "tagline": str(entry.get("tagline") or "")}
        for mbti, entry in sorted(profiles.items())
    ]
    return JSONResponse({"items": items})


@router.delete("/devices/{device_id}")
async def admin_delete_device(device_id: str, repo=Depends(get_repo)):
    await repo.soft_delete_device(device_id)
    return JSONResponse({"ok": True})


@router.post("/devices/{device_id}/rotate-secret")
async def admin_rotate_device_secret(device_id: str, repo=Depends(get_repo)):
    return JSONResponse(await repo.rotate_device_secret(device_id))


@router.post("/devices/{device_id}/reset-claim")
async def admin_reset_claim_code(device_id: str, repo=Depends(get_repo)):
    return JSONResponse(await repo.reset_claim_code(device_id))


@router.get("/devices/{device_id}/secret")
async def admin_reveal_device_secret(device_id: str, repo=Depends(get_repo)):
    return JSONResponse(await repo.reveal_device_secret(device_id))


@router.get("/voice-demo/targets")
async def admin_voice_demo_targets(repo=Depends(get_repo)):
    return JSONResponse(await repo.list_voice_demo_targets())


@router.get("/users")
async def admin_list_users(limit: int = 50, cursor: str = "", q: str = "", repo=Depends(get_repo)):
    return JSONResponse(await repo.list_users(limit=limit, cursor=cursor, q=q))


@router.post("/users")
async def admin_upsert_user(request: Request, repo=Depends(get_repo)):
    payload = await request.json()
    return JSONResponse(await repo.upsert_user(payload))


@router.delete("/users/{user_id}")
async def admin_delete_user(user_id: str, repo=Depends(get_repo)):
    await repo.soft_delete_user(user_id)
    return JSONResponse({"ok": True})


@router.get("/users/{user_id}/quota")
async def admin_user_quota(user_id: str, repo=Depends(get_repo)):
    return JSONResponse(await repo.get_user_quota_by_user_id(user_id, admin_detail=True))


@router.get("/payment/plans")
async def admin_list_payment_plans(repo=Depends(get_repo)):
    plans = await repo.list_payment_plans(include_disabled=True)
    return JSONResponse({"items": [plan.to_admin_dict() for plan in plans]})


@router.post("/payment/plans")
async def admin_create_payment_plan(request: Request, repo=Depends(get_repo)):
    payload = await request.json()
    return JSONResponse(await repo.create_payment_plan(payload))


@router.patch("/payment/plans/{plan_id}")
async def admin_update_payment_plan(plan_id: str, request: Request, repo=Depends(get_repo)):
    payload = await request.json()
    return JSONResponse(await repo.update_payment_plan(plan_id, payload))


@router.delete("/payment/plans/{plan_id}")
async def admin_delete_payment_plan(plan_id: str, repo=Depends(get_repo)):
    return JSONResponse(await repo.soft_delete_payment_plan(plan_id))


@router.get("/platform/payment-settings")
async def admin_get_payment_settings(repo=Depends(get_repo)):
    return JSONResponse(await repo.get_payment_settings())


@router.patch("/platform/payment-settings")
async def admin_update_payment_settings(request: Request, repo=Depends(get_repo)):
    payload = await request.json()
    ratio = float(payload.get("credit_ratio") or 0)
    return JSONResponse(await repo.set_credit_ratio(ratio))


@router.post("/users/{user_id}/quota/top-up")
async def admin_user_quota_top_up(user_id: str, request: Request, repo=Depends(get_repo)):
    payload = await request.json()
    return JSONResponse(
        await repo.top_up_user_dmx_quota(
            user_id,
            add_yuan=float(payload.get("add_yuan") or 0),
            note=str(payload.get("note") or ""),
        )
    )


@router.get("/platform/llm-defaults")
async def admin_platform_llm_defaults():
    return JSONResponse(default_platform_llm_config())


@router.get("/billing/summary")
async def admin_billing_summary(month: str = "", repo=Depends(get_repo)):
    if not month:
        raise ValueError("month parameter is required (YYYY-MM)")
    data = await repo.get_monthly_expenditure_summary(month)
    return JSONResponse({"success": True, "data": data})


@router.get("/billing/records")
async def admin_billing_records(
    month: str = "",
    user_id: str = "",
    limit: int = 20,
    cursor: str = "",
    repo=Depends(get_repo),
):
    if not month:
        raise ValueError("month parameter is required (YYYY-MM)")
    data = await repo.list_expenditures(
        month_str=month, user_id=user_id, limit=limit, cursor=cursor
    )
    return JSONResponse({"success": True, "data": data})


@router.delete("/billing/records/{id}")
async def admin_delete_billing_record(id: str, repo=Depends(get_repo)):
    ok = await repo.delete_expenditure(id)
    return JSONResponse({"success": ok})


@router.delete("/billing/records/months/{year_month}")
async def admin_clear_monthly_billing(year_month: str, repo=Depends(get_repo)):
    count = await repo.delete_monthly_expenditures(year_month)
    return JSONResponse({"success": True, "deleted_count": count})


@router.get("/billing/pricing")
async def admin_get_billing_pricing(repo=Depends(get_repo)):
    data = await repo.get_all_pricing()
    return JSONResponse({"success": True, "data": data})


@router.patch("/billing/pricing")
async def admin_update_billing_pricing(request: Request, repo=Depends(get_repo)):
    payload = await request.json()
    for ptype, pdict in payload.items():
        if ptype in ("stt", "tts", "llm") and isinstance(pdict, dict):
            cleaned_dict = {str(k): float(v) for k, v in pdict.items()}
            await repo.update_pricing(ptype, cleaned_dict)
            billing_svc = getattr(request.app.state, "billing", None)
            if billing_svc is not None:
                billing_svc.invalidate_cache(ptype)
    return JSONResponse({"success": True})


@router.get("/bindings")
async def admin_list_bindings(limit: int = 50, cursor: str = "", q: str = "", repo=Depends(get_repo)):
    return JSONResponse(await repo.list_bindings(limit=limit, cursor=cursor, q=q))


@router.post("/bindings")
async def admin_bind_device(request: Request, repo=Depends(get_repo)):
    payload = await request.json()
    return JSONResponse(
        await repo.admin_bind_device(
            user_id=str(payload.get("user_id") or ""),
            device_id=str(payload.get("device_id") or payload.get("device_code") or ""),
        )
    )


@router.post("/bindings/unbind")
async def admin_unbind_device(request: Request, repo=Depends(get_repo)):
    payload = await request.json()
    return JSONResponse(
        await repo.admin_unbind_device(binding_id=str(payload.get("binding_id") or ""))
    )


@router.get("/adapters")
async def admin_adapters(request: Request):
    adapter_registry = getattr(request.app.state, "adapter_registry", None)
    if adapter_registry is None:
        raise RuntimeError("adapter registry not found")
    return JSONResponse({"items": adapter_registry.list_adapters()})


@router.post("/adapters/{adapter_name}/{action}")
async def admin_call_adapter(request: Request, adapter_name: str, action: str, repo=Depends(get_repo)):
    adapter_registry = getattr(request.app.state, "adapter_registry", None)
    if adapter_registry is None:
        raise RuntimeError("adapter registry not found")
    payload = await request.json()
    result = adapter_registry.call(adapter_name, action, payload)
    
    try:
        await repo.record_adapter_action(
            adapter_name=adapter_name,
            action=action,
            request_json=payload,
            result_json=result,
        )
    except Exception as exc:
        try:
            await repo.record_adapter_action(
                adapter_name=adapter_name,
                action=action,
                request_json={},
                error=str(exc),
            )
        except Exception:
            pass
        raise
    return JSONResponse({"result": result})


@router.post("/call-test/seed")
async def admin_seed_call_test(request: Request):
    """Seed in-memory shuxin_handle / contacts for RTC call lab (process-local)."""
    from shuxin.voice.persistence import call_memory

    try:
        payload = await request.json()
    except Exception:
        payload = {}
    handles = payload.get("handles") or []
    contacts = payload.get("contacts") or []
    for item in handles:
        user_id = str((item or {}).get("user_id") or "").strip()
        handle = str((item or {}).get("handle") or "").strip()
        if user_id and handle:
            call_memory.seed_user_handle(user_id, handle)
    for item in contacts:
        owner = str((item or {}).get("owner_user_id") or "").strip()
        nickname = str((item or {}).get("nickname") or "").strip()
        target = str((item or {}).get("target_handle") or "").strip()
        if owner and nickname and target:
            call_memory.seed_contact(owner, nickname, target)
    return JSONResponse(
        {
            "ok": True,
            "handles": len(handles),
            "contacts": len(contacts),
            "note": "In-memory only; restart clears. Prefer Postgres when wired.",
        }
    )
