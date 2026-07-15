from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from shuxin.voice.api.routers.deps import get_repo, require_admin

logger = logging.getLogger("shuxin.voice.api.routers.mall_admin")

router = APIRouter(
    prefix="/admin/api/mall",
    dependencies=[Depends(require_admin)],
    tags=["Mall Admin"],
)


@router.get("/products")
async def admin_mall_products(limit: int = 50, repo=Depends(get_repo)):
    return JSONResponse(await repo.mall.admin_list_products(limit=limit))


@router.post("/products")
async def admin_mall_upsert_product(request: Request, repo=Depends(get_repo)):
    payload = await request.json()
    return JSONResponse(await repo.mall.admin_upsert_product(payload))


@router.get("/orders")
async def admin_mall_orders(limit: int = 50, repo=Depends(get_repo)):
    return JSONResponse(await repo.mall.admin_list_orders(limit=limit))


@router.post("/orders/ship")
async def admin_mall_ship_order(request: Request, repo=Depends(get_repo)):
    payload = await request.json()
    return JSONResponse(
        await repo.mall.admin_ship_order(
            order_id=str(payload.get("order_id") or ""),
            shipping_no=str(payload.get("shipping_no") or ""),
        )
    )
