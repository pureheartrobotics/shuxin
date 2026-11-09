from __future__ import annotations

from typing import Any


class MallLocalRepository:
    """YAML/demo fallback when DATABASE_URL is unset."""

    def __init__(self, *, parent: Any) -> None:
        self.parent = parent

    async def list_products(self, *, limit: int = 50) -> dict[str, Any]:
        return {"items": []}

    async def get_product(self, product_id: str) -> dict[str, Any]:
        raise ValueError(f"product not found: {product_id}")

    async def list_cart(self, *, session_token: str) -> dict[str, Any]:
        return {"items": [], "total_fen": 0, "total_yuan": 0}

    async def upsert_cart_item(
        self,
        *,
        session_token: str,
        sku_id: str,
        quantity: int,
    ) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for mall cart")

    async def remove_cart_item(self, *, session_token: str, cart_item_id: str) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for mall cart")

    async def list_addresses(self, *, session_token: str) -> dict[str, Any]:
        return {"items": []}

    async def create_address(self, *, session_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for mall addresses")

    async def update_address(
        self,
        *,
        session_token: str,
        address_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for mall addresses")

    async def delete_address(self, *, session_token: str, address_id: str) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for mall addresses")

    async def set_default_address(self, *, session_token: str, address_id: str) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for mall addresses")

    async def cancel_order(self, *, session_token: str, order_id: str) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for mall orders")

    async def list_orders_by_session(self, *, session_token: str, limit: int = 20) -> dict[str, Any]:
        return {"items": []}

    async def create_order_from_cart(
        self,
        *,
        session_token: str,
        address_id: str,
    ) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for mall orders")

    async def attach_mall_prepay_id(self, *, out_trade_no: str, prepay_id: str) -> None:
        raise RuntimeError("DATABASE_URL is required for mall payment")

    async def fulfill_mall_order(
        self,
        *,
        out_trade_no: str,
        wx_transaction_id: str,
        notify_payload: dict[str, Any],
    ) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for mall payment")

    async def admin_list_products(self, *, limit: int = 50) -> dict[str, Any]:
        return {"items": []}

    async def admin_upsert_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for mall admin")

    async def admin_upsert_sku(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for mall admin")

    async def admin_list_orders(self, *, limit: int = 50) -> dict[str, Any]:
        return {"items": []}

    async def admin_ship_order(
        self,
        *,
        order_id: str,
        shipping_no: str,
        shipping_carrier: str = "",
    ) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for mall admin")