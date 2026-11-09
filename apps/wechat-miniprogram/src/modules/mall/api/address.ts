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

export async function updateAddress(addressId: string, payload: Record<string, unknown>) {
  const session_token = requireSession();
  return request("/api/mall/addresses/update", {
    method: "POST",
    data: { session_token, address_id: addressId, ...payload },
  });
}

export async function deleteAddress(addressId: string) {
  const session_token = requireSession();
  return request("/api/mall/addresses/delete", {
    method: "POST",
    data: { session_token, address_id: addressId },
  });
}

export async function setDefaultAddress(addressId: string) {
  const session_token = requireSession();
  return request("/api/mall/addresses/set-default", {
    method: "POST",
    data: { session_token, address_id: addressId },
  });
}
