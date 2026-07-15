import { request } from "../../../core/http";
import { requireSession } from "../../../core/auth";

export async function fetchCart() {
  const session_token = requireSession();
  return request("/api/mall/cart", {
    method: "POST",
    data: { session_token },
  });
}

export async function upsertCartItem(skuId: string, quantity: number) {
  const session_token = requireSession();
  return request("/api/mall/cart/upsert", {
    method: "POST",
    data: { session_token, sku_id: skuId, quantity },
  });
}

export async function removeCartItem(cartItemId: string) {
  const session_token = requireSession();
  return request("/api/mall/cart/remove", {
    method: "POST",
    data: { session_token, cart_item_id: cartItemId },
  });
}
