import { request } from "../../../core/http";
import { requireSession } from "../../../core/auth";
import { invokeWechatPay } from "../../account/api/payment-quota";

export async function fetchOrders(limit = 20) {
  const session_token = requireSession();
  return request("/api/mall/orders", {
    method: "POST",
    data: { session_token, limit },
  });
}

export async function createMallOrder(addressId: string) {
  const session_token = requireSession();
  const result: any = await request("/api/mall/orders/create", {
    method: "POST",
    data: { session_token, address_id: addressId },
  });
  if (result.pay_params) {
    await invokeWechatPay(result.pay_params);
  }
  return result;
}
