from __future__ import annotations

import json
import os
import uuid
from typing import Any, Optional

from shuxin.voice.persistence.base_repo import (
    BaseRepository,
    _dt_iso,
    _hash_secret,
    _json_obj,
)
from shuxin.voice.persistence.users import validate_user_id


def _product_item(row: Any, skus: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "product_id": str(row["product_id"]),
        "name": str(row["name"]),
        "description": str(row.get("description") or ""),
        "cover_url": str(row.get("cover_url") or ""),
        "status": str(row.get("status") or "on_sale"),
        "sort_order": int(row.get("sort_order") or 0),
        "skus": skus or [],
        "created_at": _dt_iso(row.get("created_at")),
        "updated_at": _dt_iso(row.get("updated_at")),
    }


def _sku_item(row: Any) -> dict[str, Any]:
    return {
        "sku_id": str(row["sku_id"]),
        "product_id": str(row["product_id"]),
        "name": str(row.get("name") or ""),
        "price_fen": int(row["price_fen"]),
        "price_yuan": round(int(row["price_fen"]) / 100.0, 2),
        "stock": int(row.get("stock") or 0),
        "attrs": _json_obj(row.get("attrs")),
        "status": str(row.get("status") or "active"),
    }


def _cart_item(row: Any) -> dict[str, Any]:
    return {
        "cart_item_id": str(row["cart_item_id"]),
        "sku_id": str(row["sku_id"]),
        "product_id": str(row.get("product_id") or ""),
        "product_name": str(row.get("product_name") or ""),
        "sku_name": str(row.get("sku_name") or ""),
        "cover_url": str(row.get("cover_url") or ""),
        "price_fen": int(row.get("price_fen") or 0),
        "price_yuan": round(int(row.get("price_fen") or 0) / 100.0, 2),
        "quantity": int(row.get("quantity") or 1),
        "stock": int(row.get("stock") or 0),
    }


def _address_item(row: Any) -> dict[str, Any]:
    return {
        "address_id": str(row["address_id"]),
        "receiver_name": str(row["receiver_name"]),
        "receiver_phone": str(row["receiver_phone"]),
        "province": str(row.get("province") or ""),
        "city": str(row.get("city") or ""),
        "district": str(row.get("district") or ""),
        "detail": str(row.get("detail") or ""),
        "is_default": bool(row.get("is_default")),
        "created_at": _dt_iso(row.get("created_at")),
    }


def _order_item(row: Any, items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "order_id": str(row["order_id"]),
        "out_trade_no": str(row["out_trade_no"]),
        "status": str(row.get("status") or "pending"),
        "total_fen": int(row.get("total_fen") or 0),
        "total_yuan": round(int(row.get("total_fen") or 0) / 100.0, 2),
        "address_snapshot": _json_obj(row.get("address_snapshot")),
        "shipping_carrier": str(row.get("shipping_carrier") or ""),
        "shipping_no": str(row.get("shipping_no") or ""),
        "items": items or [],
        "created_at": _dt_iso(row.get("created_at")),
        "paid_at": _dt_iso(row.get("paid_at")) if row.get("paid_at") else None,
        "shipped_at": _dt_iso(row.get("shipped_at")) if row.get("shipped_at") else None,
    }


class MallRepository(BaseRepository):
    """商城领域数据访问。"""

    async def _user_id_from_session(self, conn, session_token: str) -> str:
        selected = str(session_token or "").strip()
        if not selected:
            raise PermissionError("session_token is required")
        user_id = await conn.fetchval(
            """
            SELECT user_id
            FROM wechat_sessions
            WHERE session_token_hash = $1
              AND expires_at > now()
            """,
            _hash_secret(selected),
        )
        if not user_id:
            raise PermissionError("session_token is invalid or expired")
        return validate_user_id(str(user_id))

    async def list_products(self, *, limit: int = 50) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT product_id, name, description, cover_url, status, sort_order,
                       created_at, updated_at
                FROM mall_products
                WHERE status = 'on_sale'
                ORDER BY sort_order DESC, created_at DESC
                LIMIT $1
                """,
                max(1, min(limit, 100)),
            )
            items = []
            for row in rows:
                sku_rows = await conn.fetch(
                    """
                    SELECT sku_id, product_id, name, price_fen, stock, attrs, status
                    FROM mall_skus
                    WHERE product_id = $1 AND status = 'active' AND stock > 0
                    ORDER BY price_fen ASC
                    """,
                    row["product_id"],
                )
                skus = [_sku_item(s) for s in sku_rows]
                item = _product_item(row, skus)
                if skus:
                    item["min_price_fen"] = min(s["price_fen"] for s in skus)
                    item["min_price_yuan"] = round(item["min_price_fen"] / 100.0, 2)
                items.append(item)
            return {"items": items}

    async def get_product(self, product_id: str) -> dict[str, Any]:
        selected = str(product_id or "").strip()
        if not selected:
            raise ValueError("product_id is required")
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT product_id, name, description, cover_url, status, sort_order,
                       created_at, updated_at
                FROM mall_products
                WHERE product_id = $1 AND status = 'on_sale'
                """,
                selected,
            )
            if row is None:
                raise ValueError(f"product not found: {selected}")
            sku_rows = await conn.fetch(
                """
                SELECT sku_id, product_id, name, price_fen, stock, attrs, status
                FROM mall_skus
                WHERE product_id = $1 AND status = 'active'
                ORDER BY price_fen ASC
                """,
                selected,
            )
            return _product_item(row, [_sku_item(s) for s in sku_rows])

    async def list_cart(self, *, session_token: str) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            user_id = await self._user_id_from_session(conn, session_token)
            rows = await conn.fetch(
                """
                SELECT c.cart_item_id, c.sku_id, c.quantity,
                       s.product_id, s.name AS sku_name, s.price_fen, s.stock,
                       p.name AS product_name, p.cover_url
                FROM mall_cart_items c
                JOIN mall_skus s ON s.sku_id = c.sku_id
                JOIN mall_products p ON p.product_id = s.product_id
                WHERE c.user_id = $1
                ORDER BY c.updated_at DESC
                """,
                user_id,
            )
            items = [_cart_item(r) for r in rows]
            total_fen = sum(int(i["price_fen"]) * int(i["quantity"]) for i in items)
            return {
                "items": items,
                "total_fen": total_fen,
                "total_yuan": round(total_fen / 100.0, 2),
            }

    async def upsert_cart_item(
        self,
        *,
        session_token: str,
        sku_id: str,
        quantity: int,
    ) -> dict[str, Any]:
        selected_sku = str(sku_id or "").strip()
        qty = int(quantity or 0)
        if not selected_sku:
            raise ValueError("sku_id is required")
        if qty <= 0:
            raise ValueError("quantity must be positive")
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                user_id = await self._user_id_from_session(conn, session_token)
                sku = await conn.fetchrow(
                    """
                    SELECT s.sku_id, s.stock, s.status, p.status AS product_status
                    FROM mall_skus s
                    JOIN mall_products p ON p.product_id = s.product_id
                    WHERE s.sku_id = $1
                    """,
                    selected_sku,
                )
                if sku is None:
                    raise ValueError(f"sku not found: {selected_sku}")
                if str(sku["status"]) != "active" or str(sku["product_status"]) != "on_sale":
                    raise ValueError("sku is not available")
                if int(sku["stock"]) < qty:
                    raise ValueError("insufficient stock")
                cart_item_id = f"ci_{uuid.uuid4().hex[:24]}"
                await conn.execute(
                    """
                    INSERT INTO mall_cart_items (cart_item_id, user_id, sku_id, quantity)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (user_id, sku_id) DO UPDATE
                    SET quantity = EXCLUDED.quantity, updated_at = now()
                    """,
                    cart_item_id,
                    user_id,
                    selected_sku,
                    qty,
                )
        return await self.list_cart(session_token=session_token)

    async def remove_cart_item(self, *, session_token: str, cart_item_id: str) -> dict[str, Any]:
        selected = str(cart_item_id or "").strip()
        if not selected:
            raise ValueError("cart_item_id is required")
        async with self.pool.acquire() as conn:
            user_id = await self._user_id_from_session(conn, session_token)
            await conn.execute(
                """
                DELETE FROM mall_cart_items
                WHERE cart_item_id = $1 AND user_id = $2
                """,
                selected,
                user_id,
            )
        return await self.list_cart(session_token=session_token)

    async def list_addresses(self, *, session_token: str) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            user_id = await self._user_id_from_session(conn, session_token)
            rows = await conn.fetch(
                """
                SELECT address_id, receiver_name, receiver_phone, province, city,
                       district, detail, is_default, created_at
                FROM mall_addresses
                WHERE user_id = $1
                ORDER BY is_default DESC, created_at DESC
                """,
                user_id,
            )
            return {"items": [_address_item(r) for r in rows]}

    async def create_address(self, *, session_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                user_id = await self._user_id_from_session(conn, session_token)
                address_id = f"addr_{uuid.uuid4().hex[:24]}"
                is_default = bool(payload.get("is_default"))
                if is_default:
                    await conn.execute(
                        "UPDATE mall_addresses SET is_default = false WHERE user_id = $1",
                        user_id,
                    )
                await conn.execute(
                    """
                    INSERT INTO mall_addresses (
                        address_id, user_id, receiver_name, receiver_phone,
                        province, city, district, detail, is_default
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    address_id,
                    user_id,
                    str(payload.get("receiver_name") or "").strip(),
                    str(payload.get("receiver_phone") or "").strip(),
                    str(payload.get("province") or "").strip(),
                    str(payload.get("city") or "").strip(),
                    str(payload.get("district") or "").strip(),
                    str(payload.get("detail") or "").strip(),
                    is_default,
                )
        return await self.list_addresses(session_token=session_token)

    async def update_address(
        self,
        *,
        session_token: str,
        address_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        selected = str(address_id or "").strip()
        if not selected:
            raise ValueError("address_id is required")
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                user_id = await self._user_id_from_session(conn, session_token)
                is_default = bool(payload.get("is_default"))
                if is_default:
                    await conn.execute(
                        "UPDATE mall_addresses SET is_default = false WHERE user_id = $1",
                        user_id,
                    )
                row = await conn.fetchrow(
                    """
                    UPDATE mall_addresses SET
                        receiver_name = $3,
                        receiver_phone = $4,
                        province = $5,
                        city = $6,
                        district = $7,
                        detail = $8,
                        is_default = $9,
                        updated_at = now()
                    WHERE address_id = $1 AND user_id = $2
                    RETURNING address_id
                    """,
                    selected,
                    user_id,
                    str(payload.get("receiver_name") or "").strip(),
                    str(payload.get("receiver_phone") or "").strip(),
                    str(payload.get("province") or "").strip(),
                    str(payload.get("city") or "").strip(),
                    str(payload.get("district") or "").strip(),
                    str(payload.get("detail") or "").strip(),
                    is_default,
                )
                if row is None:
                    raise ValueError("address not found")
        return await self.list_addresses(session_token=session_token)

    async def delete_address(self, *, session_token: str, address_id: str) -> dict[str, Any]:
        selected = str(address_id or "").strip()
        if not selected:
            raise ValueError("address_id is required")
        async with self.pool.acquire() as conn:
            user_id = await self._user_id_from_session(conn, session_token)
            await conn.execute(
                "DELETE FROM mall_addresses WHERE address_id = $1 AND user_id = $2",
                selected,
                user_id,
            )
        return await self.list_addresses(session_token=session_token)

    async def set_default_address(self, *, session_token: str, address_id: str) -> dict[str, Any]:
        selected = str(address_id or "").strip()
        if not selected:
            raise ValueError("address_id is required")
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                user_id = await self._user_id_from_session(conn, session_token)
                owned = await conn.fetchval(
                    "SELECT 1 FROM mall_addresses WHERE address_id = $1 AND user_id = $2",
                    selected,
                    user_id,
                )
                if not owned:
                    raise ValueError("address not found")
                await conn.execute(
                    "UPDATE mall_addresses SET is_default = false WHERE user_id = $1",
                    user_id,
                )
                await conn.execute(
                    """
                    UPDATE mall_addresses
                    SET is_default = true, updated_at = now()
                    WHERE address_id = $1 AND user_id = $2
                    """,
                    selected,
                    user_id,
                )
        return await self.list_addresses(session_token=session_token)

    def _pending_expire_minutes(self) -> int:
        try:
            return max(5, int(os.environ.get("SHUXIN_MALL_PENDING_EXPIRE_MINUTES") or 30))
        except ValueError:
            return 30

    async def expire_pending_orders(self, conn=None) -> int:
        """Cancel stale pending orders and restore reserved stock. Returns cancelled count."""
        minutes = self._pending_expire_minutes()

        async def _run(c) -> int:
            rows = await c.fetch(
                """
                SELECT order_id
                FROM mall_orders
                WHERE status = 'pending'
                  AND created_at < now() - make_interval(mins => $1)
                FOR UPDATE SKIP LOCKED
                """,
                minutes,
            )
            cancelled = 0
            for row in rows:
                await self._cancel_order_locked(c, order_id=str(row["order_id"]), user_id=None)
                cancelled += 1
            return cancelled

        if conn is not None:
            return await _run(conn)
        async with self.pool.acquire() as acquired:
            async with acquired.transaction():
                return await _run(acquired)

    async def _cancel_order_locked(
        self,
        conn,
        *,
        order_id: str,
        user_id: Optional[str],
    ) -> dict[str, Any]:
        if user_id:
            row = await conn.fetchrow(
                """
                SELECT order_id, out_trade_no, status, total_fen, address_snapshot,
                       shipping_carrier, shipping_no, created_at, paid_at, shipped_at
                FROM mall_orders
                WHERE order_id = $1 AND user_id = $2
                FOR UPDATE
                """,
                order_id,
                user_id,
            )
        else:
            row = await conn.fetchrow(
                """
                SELECT order_id, out_trade_no, status, total_fen, address_snapshot,
                       shipping_carrier, shipping_no, created_at, paid_at, shipped_at
                FROM mall_orders
                WHERE order_id = $1
                FOR UPDATE
                """,
                order_id,
            )
        if row is None:
            raise ValueError("order not found")
        if str(row["status"]) != "pending":
            raise ValueError("only pending orders can be cancelled")
        item_rows = await conn.fetch(
            """
            SELECT sku_id, quantity
            FROM mall_order_items
            WHERE order_id = $1
            """,
            order_id,
        )
        for item in item_rows:
            await conn.execute(
                """
                UPDATE mall_skus
                SET stock = stock + $1, updated_at = now()
                WHERE sku_id = $2
                """,
                int(item["quantity"]),
                str(item["sku_id"]),
            )
        updated = await conn.fetchrow(
            """
            UPDATE mall_orders
            SET status = 'cancelled', updated_at = now()
            WHERE order_id = $1
            RETURNING order_id, out_trade_no, status, total_fen, address_snapshot,
                      shipping_carrier, shipping_no, created_at, paid_at, shipped_at
            """,
            order_id,
        )
        detail_items = await conn.fetch(
            """
            SELECT product_id, sku_id, product_name, sku_name, price_fen, quantity
            FROM mall_order_items WHERE order_id = $1
            """,
            order_id,
        )
        items = [
            {
                "product_id": str(r["product_id"]),
                "sku_id": str(r["sku_id"]),
                "product_name": str(r["product_name"]),
                "sku_name": str(r["sku_name"]),
                "price_fen": int(r["price_fen"]),
                "quantity": int(r["quantity"]),
            }
            for r in detail_items
        ]
        return {"order": _order_item(updated, items)}

    async def cancel_order(self, *, session_token: str, order_id: str) -> dict[str, Any]:
        selected = str(order_id or "").strip()
        if not selected:
            raise ValueError("order_id is required")
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                user_id = await self._user_id_from_session(conn, session_token)
                return await self._cancel_order_locked(conn, order_id=selected, user_id=user_id)

    async def create_order_from_cart(
        self,
        *,
        session_token: str,
        address_id: str,
    ) -> dict[str, Any]:
        selected_address = str(address_id or "").strip()
        if not selected_address:
            raise ValueError("address_id is required")
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await self.expire_pending_orders(conn)
                user_id = await self._user_id_from_session(conn, session_token)
                address = await conn.fetchrow(
                    """
                    SELECT address_id, receiver_name, receiver_phone, province, city,
                           district, detail, is_default
                    FROM mall_addresses
                    WHERE address_id = $1 AND user_id = $2
                    """,
                    selected_address,
                    user_id,
                )
                if address is None:
                    raise ValueError("address not found")
                cart_rows = await conn.fetch(
                    """
                    SELECT c.cart_item_id, c.sku_id, c.quantity,
                           s.product_id, s.name AS sku_name, s.price_fen, s.stock,
                           p.name AS product_name
                    FROM mall_cart_items c
                    JOIN mall_skus s ON s.sku_id = c.sku_id
                    JOIN mall_products p ON p.product_id = s.product_id
                    WHERE c.user_id = $1
                    FOR UPDATE OF c, s
                    """,
                    user_id,
                )
                if not cart_rows:
                    raise ValueError("cart is empty")
                total_fen = 0
                line_items = []
                for row in cart_rows:
                    qty = int(row["quantity"])
                    stock = int(row["stock"])
                    if stock < qty:
                        raise ValueError(f"insufficient stock for sku {row['sku_id']}")
                    price_fen = int(row["price_fen"])
                    total_fen += price_fen * qty
                    line_items.append(row)
                if total_fen <= 0:
                    raise ValueError("invalid order total")
                order_id = f"mo_{uuid.uuid4().hex[:24]}"
                out_trade_no = f"mx{uuid.uuid4().hex[:28]}"
                address_snapshot = _address_item(address)
                order_row = await conn.fetchrow(
                    """
                    INSERT INTO mall_orders (
                        order_id, user_id, out_trade_no, status, total_fen, address_snapshot
                    ) VALUES ($1, $2, $3, 'pending', $4, $5::jsonb)
                    RETURNING order_id, out_trade_no, status, total_fen, address_snapshot,
                              shipping_carrier, shipping_no, created_at, paid_at, shipped_at
                    """,
                    order_id,
                    user_id,
                    out_trade_no,
                    total_fen,
                    json.dumps(address_snapshot, ensure_ascii=False),
                )
                for row in line_items:
                    await conn.execute(
                        """
                        INSERT INTO mall_order_items (
                            order_item_id, order_id, product_id, sku_id,
                            product_name, sku_name, price_fen, quantity
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        """,
                        f"oi_{uuid.uuid4().hex[:24]}",
                        order_id,
                        str(row["product_id"]),
                        str(row["sku_id"]),
                        str(row["product_name"]),
                        str(row["sku_name"]),
                        int(row["price_fen"]),
                        int(row["quantity"]),
                    )
                    await conn.execute(
                        """
                        UPDATE mall_skus
                        SET stock = stock - $1, updated_at = now()
                        WHERE sku_id = $2 AND stock >= $1
                        """,
                        int(row["quantity"]),
                        str(row["sku_id"]),
                    )
                await conn.execute(
                    "DELETE FROM mall_cart_items WHERE user_id = $1",
                    user_id,
                )
                item_rows = await conn.fetch(
                    """
                    SELECT product_id, sku_id, product_name, sku_name, price_fen, quantity
                    FROM mall_order_items
                    WHERE order_id = $1
                    """,
                    order_id,
                )
                items = [
                    {
                        "product_id": str(r["product_id"]),
                        "sku_id": str(r["sku_id"]),
                        "product_name": str(r["product_name"]),
                        "sku_name": str(r["sku_name"]),
                        "price_fen": int(r["price_fen"]),
                        "quantity": int(r["quantity"]),
                    }
                    for r in item_rows
                ]
                return {
                    "order": _order_item(order_row, items),
                    "user_id": user_id,
                }

    async def attach_mall_prepay_id(self, *, out_trade_no: str, prepay_id: str) -> None:
        await self.pool.execute(
            """
            UPDATE mall_orders
            SET wx_prepay_id = $2, updated_at = now()
            WHERE out_trade_no = $1
            """,
            str(out_trade_no),
            str(prepay_id),
        )

    async def list_orders_by_session(self, *, session_token: str, limit: int = 20) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await self.expire_pending_orders(conn)
                user_id = await self._user_id_from_session(conn, session_token)
                rows = await conn.fetch(
                    """
                    SELECT order_id, out_trade_no, status, total_fen, address_snapshot,
                           shipping_carrier, shipping_no, created_at, paid_at, shipped_at
                    FROM mall_orders
                    WHERE user_id = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    user_id,
                    max(1, min(int(limit or 20), 50)),
                )
                items = []
                for row in rows:
                    item_rows = await conn.fetch(
                        """
                        SELECT product_id, sku_id, product_name, sku_name, price_fen, quantity
                        FROM mall_order_items
                        WHERE order_id = $1
                        """,
                        row["order_id"],
                    )
                    order_items = [
                        {
                            "product_id": str(r["product_id"]),
                            "sku_id": str(r["sku_id"]),
                            "product_name": str(r["product_name"]),
                            "sku_name": str(r["sku_name"]),
                            "price_fen": int(r["price_fen"]),
                            "quantity": int(r["quantity"]),
                        }
                        for r in item_rows
                    ]
                    items.append(_order_item(row, order_items))
                return {"items": items}

    async def fulfill_mall_order(
        self,
        *,
        out_trade_no: str,
        wx_transaction_id: str,
        notify_payload: dict[str, Any],
    ) -> dict[str, Any]:
        selected = str(out_trade_no or "").strip()
        if not selected:
            raise ValueError("out_trade_no is required")
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT order_id, out_trade_no, status, total_fen, address_snapshot,
                           shipping_carrier, shipping_no, created_at, paid_at, shipped_at
                    FROM mall_orders
                    WHERE out_trade_no = $1
                    FOR UPDATE
                    """,
                    selected,
                )
                if row is None:
                    raise ValueError(f"mall order not found: {selected}")
                if str(row["status"]) == "paid":
                    item_rows = await conn.fetch(
                        """
                        SELECT product_id, sku_id, product_name, sku_name, price_fen, quantity
                        FROM mall_order_items WHERE order_id = $1
                        """,
                        row["order_id"],
                    )
                    items = [
                        {
                            "product_id": str(r["product_id"]),
                            "sku_id": str(r["sku_id"]),
                            "product_name": str(r["product_name"]),
                            "sku_name": str(r["sku_name"]),
                            "price_fen": int(r["price_fen"]),
                            "quantity": int(r["quantity"]),
                        }
                        for r in item_rows
                    ]
                    return {"order": _order_item(row, items), "already_fulfilled": True}
                if str(row["status"]) != "pending":
                    raise ValueError(f"mall order not payable: status={row['status']}")
                updated = await conn.fetchrow(
                    """
                    UPDATE mall_orders
                    SET status = 'paid',
                        wx_transaction_id = $2,
                        notify_payload = $3::jsonb,
                        paid_at = now(),
                        updated_at = now()
                    WHERE out_trade_no = $1
                    RETURNING order_id, out_trade_no, status, total_fen, address_snapshot,
                              shipping_carrier, shipping_no, created_at, paid_at, shipped_at
                    """,
                    selected,
                    str(wx_transaction_id or ""),
                    json.dumps(notify_payload or {}, ensure_ascii=False),
                )
                item_rows = await conn.fetch(
                    """
                    SELECT product_id, sku_id, product_name, sku_name, price_fen, quantity
                    FROM mall_order_items WHERE order_id = $1
                    """,
                    updated["order_id"],
                )
                items = [
                    {
                        "product_id": str(r["product_id"]),
                        "sku_id": str(r["sku_id"]),
                        "product_name": str(r["product_name"]),
                        "sku_name": str(r["sku_name"]),
                        "price_fen": int(r["price_fen"]),
                        "quantity": int(r["quantity"]),
                    }
                    for r in item_rows
                ]
                return {"order": _order_item(updated, items), "already_fulfilled": False}

    async def admin_list_products(self, *, limit: int = 50) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT product_id, name, description, cover_url, status, sort_order,
                       created_at, updated_at
                FROM mall_products
                ORDER BY sort_order DESC, created_at DESC
                LIMIT $1
                """,
                max(1, min(limit, 200)),
            )
            items = []
            for row in rows:
                sku_rows = await conn.fetch(
                    """
                    SELECT sku_id, product_id, name, price_fen, stock, attrs, status
                    FROM mall_skus
                    WHERE product_id = $1
                    ORDER BY created_at ASC
                    """,
                    row["product_id"],
                )
                items.append(_product_item(row, [_sku_item(s) for s in sku_rows]))
            return {"items": items}

    async def admin_upsert_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        product_id = str(payload.get("product_id") or f"mp_{uuid.uuid4().hex[:24]}").strip()
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("name is required")
        status = str(payload.get("status") or "on_sale").strip()
        if status not in ("on_sale", "off_sale"):
            raise ValueError("invalid product status")
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    INSERT INTO mall_products (
                        product_id, name, description, cover_url, status, sort_order
                    ) VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (product_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        description = EXCLUDED.description,
                        cover_url = EXCLUDED.cover_url,
                        status = EXCLUDED.status,
                        sort_order = EXCLUDED.sort_order,
                        updated_at = now()
                    RETURNING product_id, name, description, cover_url, status, sort_order,
                              created_at, updated_at
                    """,
                    product_id,
                    name,
                    str(payload.get("description") or ""),
                    str(payload.get("cover_url") or ""),
                    status,
                    int(payload.get("sort_order") or 0),
                )
                skus_payload = payload.get("skus")
                if isinstance(skus_payload, list):
                    for sku in skus_payload:
                        if not isinstance(sku, dict):
                            continue
                        await self._upsert_sku_conn(conn, product_id=product_id, payload=sku)
                else:
                    price_fen = int(payload.get("price_fen") or 0)
                    stock = int(payload.get("stock") or 0)
                    if price_fen > 0:
                        await self._upsert_sku_conn(
                            conn,
                            product_id=product_id,
                            payload={
                                "sku_id": payload.get("sku_id"),
                                "name": payload.get("sku_name") or "默认",
                                "price_fen": price_fen,
                                "stock": stock,
                                "attrs": payload.get("attrs") or {},
                                "status": "active",
                            },
                        )
                sku_rows = await conn.fetch(
                    """
                    SELECT sku_id, product_id, name, price_fen, stock, attrs, status
                    FROM mall_skus WHERE product_id = $1 ORDER BY created_at ASC
                    """,
                    product_id,
                )
                return _product_item(row, [_sku_item(s) for s in sku_rows])

    async def _upsert_sku_conn(self, conn, *, product_id: str, payload: dict[str, Any]) -> str:
        sku_id = str(payload.get("sku_id") or f"ms_{uuid.uuid4().hex[:24]}").strip()
        price_fen = int(payload.get("price_fen") or 0)
        if price_fen <= 0:
            raise ValueError("sku price_fen must be positive")
        status = str(payload.get("status") or "active").strip()
        if status not in ("active", "inactive"):
            raise ValueError("invalid sku status")
        attrs = payload.get("attrs") if isinstance(payload.get("attrs"), dict) else {}
        await conn.execute(
            """
            INSERT INTO mall_skus (
                sku_id, product_id, name, price_fen, stock, attrs, status
            ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
            ON CONFLICT (sku_id) DO UPDATE SET
                name = EXCLUDED.name,
                price_fen = EXCLUDED.price_fen,
                stock = EXCLUDED.stock,
                attrs = EXCLUDED.attrs,
                status = EXCLUDED.status,
                updated_at = now()
            """,
            sku_id,
            product_id,
            str(payload.get("name") or "").strip() or "默认",
            price_fen,
            max(0, int(payload.get("stock") or 0)),
            json.dumps(attrs, ensure_ascii=False),
            status,
        )
        return sku_id

    async def admin_upsert_sku(self, payload: dict[str, Any]) -> dict[str, Any]:
        product_id = str(payload.get("product_id") or "").strip()
        if not product_id:
            raise ValueError("product_id is required")
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                exists = await conn.fetchval(
                    "SELECT 1 FROM mall_products WHERE product_id = $1",
                    product_id,
                )
                if not exists:
                    raise ValueError("product not found")
                sku_id = await self._upsert_sku_conn(conn, product_id=product_id, payload=payload)
                row = await conn.fetchrow(
                    """
                    SELECT sku_id, product_id, name, price_fen, stock, attrs, status
                    FROM mall_skus WHERE sku_id = $1
                    """,
                    sku_id,
                )
                return {"sku": _sku_item(row)}

    async def admin_list_orders(self, *, limit: int = 50) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await self.expire_pending_orders(conn)
                rows = await conn.fetch(
                    """
                    SELECT order_id, out_trade_no, status, total_fen, address_snapshot,
                           shipping_carrier, shipping_no, created_at, paid_at, shipped_at, user_id
                    FROM mall_orders
                    ORDER BY created_at DESC
                    LIMIT $1
                    """,
                    max(1, min(limit, 200)),
                )
                items = []
                for row in rows:
                    item_rows = await conn.fetch(
                        """
                        SELECT product_id, sku_id, product_name, sku_name, price_fen, quantity
                        FROM mall_order_items WHERE order_id = $1
                        """,
                        row["order_id"],
                    )
                    order_items = [
                        {
                            "product_id": str(r["product_id"]),
                            "sku_id": str(r["sku_id"]),
                            "product_name": str(r["product_name"]),
                            "sku_name": str(r["sku_name"]),
                            "price_fen": int(r["price_fen"]),
                            "quantity": int(r["quantity"]),
                        }
                        for r in item_rows
                    ]
                    item = _order_item(row, order_items)
                    item["user_id"] = str(row["user_id"])
                    items.append(item)
                return {"items": items}

    async def admin_ship_order(
        self,
        *,
        order_id: str,
        shipping_no: str,
        shipping_carrier: str = "",
    ) -> dict[str, Any]:
        selected = str(order_id or "").strip()
        if not selected:
            raise ValueError("order_id is required")
        carrier = str(shipping_carrier or "").strip()
        tracking = str(shipping_no or "").strip()
        if not tracking:
            raise ValueError("shipping_no is required")
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE mall_orders
                SET status = 'shipped',
                    shipping_carrier = $2,
                    shipping_no = $3,
                    shipped_at = now(),
                    updated_at = now()
                WHERE order_id = $1 AND status IN ('paid', 'shipped')
                RETURNING order_id, out_trade_no, status, total_fen, address_snapshot,
                          shipping_carrier, shipping_no, created_at, paid_at, shipped_at
                """,
                selected,
                carrier,
                tracking,
            )
            if row is None:
                raise ValueError("order not found or not shippable")
            return {"order": _order_item(row)}