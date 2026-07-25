const API_BASE = import.meta.env.VITE_SHUXIN_API_BASE || "http://localhost:8765";

export type HttpMethod = "GET" | "POST";

export type RequestOptions = {
  method?: HttpMethod;
  data?: Record<string, unknown>;
  auth?: boolean;
};

export class ApiError extends Error {
  code: string;
  statusCode: number;
  detail: string;
  body: Record<string, unknown>;

  constructor(
    message: string,
    opts: {
      code?: string;
      statusCode?: number;
      detail?: string;
      body?: Record<string, unknown>;
    } = {}
  ) {
    super(message);
    this.name = "ApiError";
    this.code = String(opts.code || message || "error");
    this.statusCode = Number(opts.statusCode || 0);
    this.detail = String(opts.detail || message || "");
    this.body = opts.body || {};
  }
}

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
        reject(
          new ApiError(String(body?.detail || errorMsg), {
            code: String(errorMsg),
            statusCode: Number(res.statusCode || 0),
            detail: String(body?.detail || errorMsg),
            body: body && typeof body === "object" ? body : {},
          })
        );
      },
      fail: (error) => reject(new Error(error.errMsg || "请求失败")),
    });
  });
}

export function getApiBase(): string {
  return API_BASE;
}
