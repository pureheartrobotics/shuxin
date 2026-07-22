import { request } from "../../core/http";
import { requireSession } from "../../core/auth";

export async function fetchGachaConfig() {
  const session_token = requireSession();
  return request("/api/gacha/config", { method: "POST", data: { session_token } });
}

export async function drawGacha(payment_id?: string) {
  const session_token = requireSession();
  return request("/api/gacha/draw", {
    method: "POST",
    data: { session_token, payment_id: payment_id || null },
  });
}

export async function createGachaOrder() {
  const session_token = requireSession();
  return request("/api/gacha/orders", { method: "POST", data: { session_token } });
}

export async function listCompanions() {
  const session_token = requireSession();
  return request("/api/companions", { method: "POST", data: { session_token } });
}

export async function renameCompanion(companion_id: string, display_name: string) {
  const session_token = requireSession();
  return request("/api/companions/rename", {
    method: "POST",
    data: { session_token, companion_id, display_name },
  });
}

export async function softCredentials() {
  const session_token = requireSession();
  return request("/api/voice/soft-credentials", {
    method: "POST",
    data: { session_token },
  });
}

export async function chatText(companion_id: string, text: string) {
  const session_token = requireSession();
  return request("/api/chat/text", {
    method: "POST",
    data: { session_token, companion_id, text },
  });
}
