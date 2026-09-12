const API_BASE = import.meta.env.VITE_SHUXIN_API_BASE || "http://localhost:8765";

export type HttpMethod = "GET" | "POST";

export type RequestOptions = {
  method?: HttpMethod;
  data?: Record<string, unknown>;
  auth?: boolean;
};

function handleSessionError(errorMsg: string): boolean {
  if (errorMsg === "session_token is invalid or expired") {
    uni.removeStorageSync("shuxin_session_token");
    uni.removeStorageSync("shuxin_session_expires_at");
    uni.removeStorageSync("shuxin_user_id");
    uni.redirectTo({ url: "/pages/login/login" });
    return true;
  }
  return false;
}

export function request<T = any>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method || (options.data ? "POST" : "GET");
  const url = `${API_BASE}${path}`;
  return new Promise((resolve, reject) => {
    uni.request({
      url,
      method,
      data: options.data,
      success: (res) => {
        const body: any = res.data;
        if (res.statusCode >= 200 && res.statusCode < 300 && !body?.error) {
          resolve(body as T);
          return;
        }
        const errorMsg = body?.error || `请求失败: ${res.statusCode}`;
        handleSessionError(String(errorMsg));
        reject(new Error(String(errorMsg)));
      },
      fail: (error) => reject(new Error(error.errMsg || "请求失败")),
    });
  });
}

export function getApiBase(): string {
  return API_BASE;
}
