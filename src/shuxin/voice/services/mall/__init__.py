from __future__ import annotations

from typing import Any


def _require_session(session_token: str) -> str:
    selected = str(session_token or "").strip()
    if not selected:
        raise PermissionError("session_token is required")
    return selected


class MallProductService:
    def __init__(self, repo: Any) -> None:
        self.repo = repo

    async def list_products(self, *, limit: int = 50) -> dict[str, Any]:
        return await self.repo.mall.list_products(limit=limit)

    async def get_product(self, product_id: str) -> dict[str, Any]:
        return await self.repo.mall.get_product(product_id)


class MallCartService:
    def __init__(self, repo: Any) -> None:
        self.repo = repo

    async def list_cart(self, *, session_token: str) -> dict[str, Any]:
        return await self.repo.mall.list_cart(session_token=_require_session(session_token))

    async def upsert_item(
        self,
        *,
        session_token: str,
        sku_id: str,
        quantity: int,
    ) -> dict[str, Any]:
        return await self.repo.mall.upsert_cart_item(
            session_token=_require_session(session_token),
            sku_id=sku_id,
            quantity=quantity,
        )

    async def remove_item(self, *, session_token: str, cart_item_id: str) -> dict[str, Any]:
        return await self.repo.mall.remove_cart_item(
            session_token=_require_session(session_token),
            cart_item_id=cart_item_id,
        )


class MallAddressService:
    def __init__(self, repo: Any) -> None:
        self.repo = repo

    async def list_addresses(self, *, session_token: str) -> dict[str, Any]:
        return await self.repo.mall.list_addresses(session_token=_require_session(session_token))

    async def create_address(self, *, session_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.repo.mall.create_address(
            session_token=_require_session(session_token),
            payload=payload,
        )

    async def update_address(
        self,
        *,
        session_token: str,
        address_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.repo.mall.update_address(
            session_token=_require_session(session_token),
            address_id=address_id,
            payload=payload,
        )

    async def delete_address(self, *, session_token: str, address_id: str) -> dict[str, Any]:
        return await self.repo.mall.delete_address(
            session_token=_require_session(session_token),
            address_id=address_id,
        )

    async def set_default_address(self, *, session_token: str, address_id: str) -> dict[str, Any]:
        return await self.repo.mall.set_default_address(
            session_token=_require_session(session_token),
            address_id=address_id,
        )


class MallOrderService:
    def __init__(self, repo: Any) -> None:
        self.repo = repo

    async def list_orders(self, *, session_token: str, limit: int = 20) -> dict[str, Any]:
        return await self.repo.mall.list_orders_by_session(
            session_token=_require_session(session_token),
            limit=limit,
        )

    async def cancel_order(self, *, session_token: str, order_id: str) -> dict[str, Any]:
        return await self.repo.mall.cancel_order(
            session_token=_require_session(session_token),
            order_id=order_id,
        )
