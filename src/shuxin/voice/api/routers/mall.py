from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from shuxin.voice.api.routers.deps import get_repo
from shuxin.voice.services.mall import (
    MallAddressService,
    MallCartService,
    MallOrderService,
    MallProductService,
)
from shuxin.voice.services.payment.mall_payment_service import MallPaymentService

logger = logging.getLogger("shuxin.voice.api.routers.mall")

router = APIRouter(tags=["Mall"])


def _products(repo=Depends(get_repo)) -> MallProductService:
    return MallProductService(repo)


def _cart(repo=Depends(get_repo)) -> MallCartService:
    return MallCartService(repo)


def _addresses(repo=Depends(get_repo)) -> MallAddressService:
    return MallAddressService(repo)


def _orders(repo=Depends(get_repo)) -> MallOrderService:
    return MallOrderService(repo)


def _payments(repo=Depends(get_repo)) -> MallPaymentService:
    return MallPaymentService(repo)


@router.get("/api/mall/products")
async def mall_products(limit: int = 50, service: MallProductService = Depends(_products)):
    return JSONResponse(await service.list_products(limit=limit))


@router.get("/api/mall/products/{product_id}")
async def mall_product_detail(product_id: str, service: MallProductService = Depends(_products)):
    return JSONResponse(await service.get_product(product_id))


@router.post("/api/mall/cart")
async def mall_cart_list(request: Request, service: MallCartService = Depends(_cart)):
    payload = await request.json()
    session_token = str(payload.get("session_token") or "")
    return JSONResponse(await service.list_cart(session_token=session_token))


@router.post("/api/mall/cart/upsert")
async def mall_cart_upsert(request: Request, service: MallCartService = Depends(_cart)):
    payload = await request.json()
    return JSONResponse(
        await service.upsert_item(
            session_token=str(payload.get("session_token") or ""),
            sku_id=str(payload.get("sku_id") or ""),
            quantity=int(payload.get("quantity") or 1),
        )
    )


@router.post("/api/mall/cart/remove")
async def mall_cart_remove(request: Request, service: MallCartService = Depends(_cart)):
    payload = await request.json()
    return JSONResponse(
        await service.remove_item(
            session_token=str(payload.get("session_token") or ""),
            cart_item_id=str(payload.get("cart_item_id") or ""),
        )
    )


@router.post("/api/mall/addresses")
async def mall_addresses_list(request: Request, service: MallAddressService = Depends(_addresses)):
    payload = await request.json()
    return JSONResponse(
        await service.list_addresses(session_token=str(payload.get("session_token") or ""))
    )


@router.post("/api/mall/addresses/create")
async def mall_addresses_create(request: Request, service: MallAddressService = Depends(_addresses)):
    payload = await request.json()
    session_token = str(payload.get("session_token") or "")
    body = {
        "receiver_name": payload.get("receiver_name"),
        "receiver_phone": payload.get("receiver_phone"),
        "province": payload.get("province"),
        "city": payload.get("city"),
        "district": payload.get("district"),
        "detail": payload.get("detail"),
        "is_default": payload.get("is_default"),
    }
    return JSONResponse(await service.create_address(session_token=session_token, payload=body))


@router.post("/api/mall/addresses/update")
async def mall_addresses_update(request: Request, service: MallAddressService = Depends(_addresses)):
    payload = await request.json()
    body = {
        "receiver_name": payload.get("receiver_name"),
        "receiver_phone": payload.get("receiver_phone"),
        "province": payload.get("province"),
        "city": payload.get("city"),
        "district": payload.get("district"),
        "detail": payload.get("detail"),
        "is_default": payload.get("is_default"),
    }
    return JSONResponse(
        await service.update_address(
            session_token=str(payload.get("session_token") or ""),
            address_id=str(payload.get("address_id") or ""),
            payload=body,
        )
    )


@router.post("/api/mall/addresses/delete")
async def mall_addresses_delete(request: Request, service: MallAddressService = Depends(_addresses)):
    payload = await request.json()
    return JSONResponse(
        await service.delete_address(
            session_token=str(payload.get("session_token") or ""),
            address_id=str(payload.get("address_id") or ""),
        )
    )


@router.post("/api/mall/addresses/set-default")
async def mall_addresses_set_default(
    request: Request, service: MallAddressService = Depends(_addresses)
):
    payload = await request.json()
    return JSONResponse(
        await service.set_default_address(
            session_token=str(payload.get("session_token") or ""),
            address_id=str(payload.get("address_id") or ""),
        )
    )


@router.post("/api/mall/orders")
async def mall_orders_list(request: Request, service: MallOrderService = Depends(_orders)):
    payload = await request.json()
    return JSONResponse(
        await service.list_orders(
            session_token=str(payload.get("session_token") or ""),
            limit=int(payload.get("limit") or 20),
        )
    )


@router.post("/api/mall/orders/cancel")
async def mall_orders_cancel(request: Request, service: MallOrderService = Depends(_orders)):
    payload = await request.json()
    return JSONResponse(
        await service.cancel_order(
            session_token=str(payload.get("session_token") or ""),
            order_id=str(payload.get("order_id") or ""),
        )
    )


@router.post("/api/mall/orders/create")
async def mall_orders_create(request: Request, service: MallPaymentService = Depends(_payments)):
    payload = await request.json()
    return await service.create_order(
        session_token=str(payload.get("session_token") or ""),
        address_id=str(payload.get("address_id") or ""),
    )
