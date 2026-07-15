import { request } from "../../../core/http";
import { requireSession } from "../../../core/auth";

export async function fetchAddresses() {
  const session_token = requireSession();
  return request("/api/mall/addresses", {
    method: "POST",
    data: { session_token },
  });
}

export async function createAddress(payload: Record<string, unknown>) {
  const session_token = requireSession();
  return request("/api/mall/addresses/create", {
    method: "POST",
    data: { session_token, ...payload },
  });
}
