from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

logger = logging.getLogger("shuxin.voice.api.miniapp_admin")

miniapp_admin_router = APIRouter()


def _get_miniapp_admin_token() -> str:
    """获取小程序管理后台 Token。

    读取 SHUXIN_MINIAPP_ADMIN_TOKEN，未设时回退 SHUXIN_ADMIN_TOKEN。
    二者皆空则返回空字符串（禁止硬编码默认值，避免未配置即可登录）。
    """
    token = (os.environ.get("SHUXIN_MINIAPP_ADMIN_TOKEN") or "").strip()
    if not token:
        token = (os.environ.get("SHUXIN_ADMIN_TOKEN") or "").strip()
    return token


def require_miniapp_admin(request: Request) -> None:
    """验证小程序管理后台登录状态。"""
    token = _get_miniapp_admin_token()
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: configure SHUXIN_MINIAPP_ADMIN_TOKEN or SHUXIN_ADMIN_TOKEN",
        )
    provided = request.headers.get("X-Miniapp-Admin-Token") or request.cookies.get(
        "shuxin_miniapp_admin"
    )
    if not provided or provided != token:
        raise HTTPException(status_code=401, detail="Unauthorized: invalid admin token")


class LoginPayload(BaseModel):
    token: str


class AnnouncementPayload(BaseModel):
    id: Optional[int] = None
    title: str
    content: str
    type: str
    is_active: bool = True
    start_time: Optional[str] = None
    end_time: Optional[str] = None


class FeedbackUpdatePayload(BaseModel):
    status: str
    admin_notes: str


class SubscriptionPlanPayload(BaseModel):
    plan_id: str
    name: str
    amount_fen: int
    duration_minutes: int
    description: Optional[str] = ""
    sort_order: Optional[int] = 0
    enabled: Optional[bool] = True


class FuelPackagePayload(BaseModel):
    package_id: str
    name: str
    amount_fen: int
    duration_minutes: int
    description: Optional[str] = ""
    sort_order: Optional[int] = 0
    enabled: Optional[bool] = True


class AllowanceSettingsPayload(BaseModel):
    daily_free_minutes: float
    enabled: bool
    gift_subscription_plan_id: Optional[str] = None
    gift_duration_months: Optional[int] = 0


@miniapp_admin_router.post("/api/login")
async def admin_login(payload: LoginPayload, response: Response):
    token = _get_miniapp_admin_token()
    if not token:
        return JSONResponse(
            {
                "error": "admin token not configured; set SHUXIN_MINIAPP_ADMIN_TOKEN or SHUXIN_ADMIN_TOKEN",
            },
            status_code=403,
        )
    if payload.token != token:
        return JSONResponse({"error": "invalid admin token"}, status_code=403)

    response.set_cookie(
        key="shuxin_miniapp_admin",
        value=token,
        max_age=86400 * 30,  # 30 days
        httponly=True,
        samesite="lax",
    )
    return {"ok": True}


@miniapp_admin_router.post("/api/logout")
async def admin_logout(response: Response):
    response.delete_cookie("shuxin_miniapp_admin")
    return {"ok": True}


@miniapp_admin_router.get("/api/announcements")
async def list_announcements(request: Request, limit: int = 50, offset: int = 0):
    require_miniapp_admin(request)
    repo = request.app.state.repo
    items = await repo.admin_list_announcements(limit=limit, offset=offset)
    return {"items": items}


@miniapp_admin_router.post("/api/announcements")
async def upsert_announcement(request: Request, payload: AnnouncementPayload):
    require_miniapp_admin(request)
    repo = request.app.state.repo

    start_dt = None
    if payload.start_time:
        try:
            start_dt = datetime.fromisoformat(payload.start_time.replace("Z", "+00:00"))
        except ValueError:
            pass

    end_dt = None
    if payload.end_time:
        try:
            end_dt = datetime.fromisoformat(payload.end_time.replace("Z", "+00:00"))
        except ValueError:
            pass

    result = await repo.admin_upsert_announcement(
        announcement_id=payload.id,
        title=payload.title,
        content=payload.content,
        type=payload.type,
        is_active=payload.is_active,
        start_time=start_dt,
        end_time=end_dt
    )
    return result


@miniapp_admin_router.delete("/api/announcements/{announcement_id}")
async def delete_announcement(request: Request, announcement_id: int):
    require_miniapp_admin(request)
    repo = request.app.state.repo
    result = await repo.admin_delete_announcement(announcement_id)
    return result


@miniapp_admin_router.get("/api/feedbacks")
async def list_feedbacks(request: Request, limit: int = 50, offset: int = 0, status: Optional[str] = None):
    require_miniapp_admin(request)
    repo = request.app.state.repo
    items = await repo.admin_list_feedbacks(limit=limit, offset=offset, status=status)
    return {"items": items}


@miniapp_admin_router.put("/api/feedbacks/{feedback_id}")
async def update_feedback(request: Request, feedback_id: int, payload: FeedbackUpdatePayload):
    require_miniapp_admin(request)
    repo = request.app.state.repo
    result = await repo.admin_update_feedback(
        feedback_id,
        status=payload.status,
        admin_notes=payload.admin_notes
    )
    return result


@miniapp_admin_router.get("/api/subscription-plans")
async def list_subscription_plans(request: Request):
    require_miniapp_admin(request)
    repo = request.app.state.repo
    items = await repo.admin_list_subscription_plans()
    return {"items": items}


@miniapp_admin_router.post("/api/subscription-plans")
async def upsert_subscription_plan(request: Request, payload: SubscriptionPlanPayload):
    require_miniapp_admin(request)
    repo = request.app.state.repo
    result = await repo.admin_upsert_subscription_plan(
        plan_id=payload.plan_id,
        name=payload.name,
        amount_fen=payload.amount_fen,
        duration_minutes=payload.duration_minutes,
        description=payload.description or "",
        sort_order=payload.sort_order or 0,
        enabled=payload.enabled if payload.enabled is not None else True
    )
    return result


@miniapp_admin_router.delete("/api/subscription-plans/{plan_id}")
async def delete_subscription_plan(request: Request, plan_id: str):
    require_miniapp_admin(request)
    repo = request.app.state.repo
    result = await repo.admin_delete_subscription_plan(plan_id)
    return result


@miniapp_admin_router.get("/api/fuel-packages")
async def list_fuel_packages(request: Request):
    require_miniapp_admin(request)
    repo = request.app.state.repo
    items = await repo.admin_list_fuel_packages()
    return {"items": items}


@miniapp_admin_router.post("/api/fuel-packages")
async def upsert_fuel_package(request: Request, payload: FuelPackagePayload):
    require_miniapp_admin(request)
    repo = request.app.state.repo
    result = await repo.admin_upsert_fuel_package(
        package_id=payload.package_id,
        name=payload.name,
        amount_fen=payload.amount_fen,
        duration_minutes=payload.duration_minutes,
        description=payload.description or "",
        sort_order=payload.sort_order or 0,
        enabled=payload.enabled if payload.enabled is not None else True
    )
    return result


@miniapp_admin_router.delete("/api/fuel-packages/{package_id}")
async def delete_fuel_package(request: Request, package_id: str):
    require_miniapp_admin(request)
    repo = request.app.state.repo
    result = await repo.admin_delete_fuel_package(package_id)
    return result


@miniapp_admin_router.get("/api/allowance-settings")
async def get_allowance_settings(request: Request):
    require_miniapp_admin(request)
    repo = request.app.state.repo
    data = await repo.admin_get_allowance_settings()
    return {"data": data}


@miniapp_admin_router.put("/api/allowance-settings")
async def update_allowance_settings(request: Request, payload: AllowanceSettingsPayload):
    require_miniapp_admin(request)
    repo = request.app.state.repo
    result = await repo.admin_update_allowance_settings(
        daily_free_minutes=payload.daily_free_minutes,
        enabled=payload.enabled,
        gift_subscription_plan_id=payload.gift_subscription_plan_id,
        gift_duration_months=payload.gift_duration_months or 0
    )
    return result


# ---- Mall (ops) ----

class MallProductPayload(BaseModel):
    product_id: Optional[str] = None
    name: str
    description: Optional[str] = ""
    cover_url: Optional[str] = ""
    status: Optional[str] = "on_sale"
    sort_order: Optional[int] = 0
    skus: Optional[list] = None
    price_fen: Optional[int] = None
    stock: Optional[int] = None
    sku_id: Optional[str] = None
    sku_name: Optional[str] = None


class MallSkuPayload(BaseModel):
    product_id: str
    sku_id: Optional[str] = None
    name: Optional[str] = "默认"
    price_fen: int
    stock: Optional[int] = 0
    attrs: Optional[dict] = None
    status: Optional[str] = "active"


class MallShipPayload(BaseModel):
    order_id: str
    shipping_no: str
    shipping_carrier: Optional[str] = ""


@miniapp_admin_router.get("/api/mall/products")
async def miniapp_mall_products(request: Request, limit: int = 50):
    require_miniapp_admin(request)
    return await request.app.state.repo.mall.admin_list_products(limit=limit)


@miniapp_admin_router.post("/api/mall/products")
async def miniapp_mall_upsert_product(request: Request, payload: MallProductPayload):
    require_miniapp_admin(request)
    data = payload.model_dump(exclude_none=True)
    return await request.app.state.repo.mall.admin_upsert_product(data)


@miniapp_admin_router.post("/api/mall/skus")
async def miniapp_mall_upsert_sku(request: Request, payload: MallSkuPayload):
    require_miniapp_admin(request)
    data = payload.model_dump(exclude_none=True)
    return await request.app.state.repo.mall.admin_upsert_sku(data)


@miniapp_admin_router.get("/api/mall/orders")
async def miniapp_mall_orders(request: Request, limit: int = 50):
    require_miniapp_admin(request)
    return await request.app.state.repo.mall.admin_list_orders(limit=limit)


@miniapp_admin_router.post("/api/mall/orders/ship")
async def miniapp_mall_ship(request: Request, payload: MallShipPayload):
    require_miniapp_admin(request)
    return await request.app.state.repo.mall.admin_ship_order(
        order_id=payload.order_id,
        shipping_no=payload.shipping_no,
        shipping_carrier=payload.shipping_carrier or "",
    )


@miniapp_admin_router.get("", response_class=HTMLResponse)
async def admin_portal(request: Request):
    """渲染精美的小程序专属后台管理界面。"""
    token = _get_miniapp_admin_token()
    provided = request.headers.get("X-Miniapp-Admin-Token") or request.cookies.get(
        "shuxin_miniapp_admin"
    )
    authenticated = bool(token) and provided == token

    static_file = Path(__file__).resolve().parent.parent / "static" / "miniapp_admin.html"
    html_content = static_file.read_text(encoding="utf-8")
    html_content = html_content.replace(
        "{{authenticated}}", "true" if authenticated else "false"
    )
    html_content = html_content.replace(
        "{{token_configured}}", "true" if bool(token) else "false"
    )
    return HTMLResponse(content=html_content)
