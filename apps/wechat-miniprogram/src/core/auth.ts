const TOKEN_KEY = "shuxin_session_token";
const EXPIRES_KEY = "shuxin_session_expires_at";
const USER_ID_KEY = "shuxin_user_id";

export function sessionToken(): string {
  const token = String(uni.getStorageSync(TOKEN_KEY) || "");
  const expiresAt = String(uni.getStorageSync(EXPIRES_KEY) || "");
  if (!token) return "";
  if (expiresAt && Date.parse(expiresAt) <= Date.now()) return "";
  return token;
}

export function isLoggedIn(): boolean {
  return Boolean(sessionToken());
}

export function saveSession(payload: {
  session_token: string;
  expires_at?: string;
  user_id?: string;
}) {
  uni.setStorageSync(TOKEN_KEY, payload.session_token);
  if (payload.expires_at) {
    uni.setStorageSync(EXPIRES_KEY, payload.expires_at);
  }
  if (payload.user_id) {
    uni.setStorageSync(USER_ID_KEY, payload.user_id);
  }
}

export function clearSession() {
  uni.removeStorageSync(TOKEN_KEY);
  uni.removeStorageSync(EXPIRES_KEY);
  uni.removeStorageSync(USER_ID_KEY);
}

export function requireSession(): string {
  const token = sessionToken();
  if (!token) {
    uni.redirectTo({ url: "/pages/login/login" });
    throw new Error("session required");
  }
  return token;
}

export function storedUserId(): string {
  return String(uni.getStorageSync(USER_ID_KEY) || "");
}
