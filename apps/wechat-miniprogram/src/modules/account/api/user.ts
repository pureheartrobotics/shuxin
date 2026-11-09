import { request } from "../../../core/http";
import { requireSession } from "../../../core/auth";

export async function fetchUserProfile() {
  const session_token = requireSession();
  return request("/api/users/me", {
    method: "POST",
    data: { session_token },
  });
}

export async function fetchMyDevices() {
  const session_token = requireSession();
  return request("/api/devices/my", {
    method: "POST",
    data: { session_token },
  });
}
