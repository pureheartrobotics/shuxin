import { ApiError, getApiBase, request } from "../../core/http";
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

export type ChatStreamHandlers = {
  onDelta: (text: string) => void;
  onDone: (body: Record<string, unknown>) => void;
  onError: (err: Error) => void;
};

function handleSessionError(errorMsg: string): boolean {
  if (errorMsg === "session_token is invalid or expired") {
    uni.removeStorageSync("shuxin_session_token");
    uni.redirectTo({ url: "/pages/login/login" });
    return true;
  }
  return false;
}

/** NDJSON stream from /api/chat/text/stream (WeChat enableChunked). */
export function chatTextStream(
  companion_id: string,
  text: string,
  handlers: ChatStreamHandlers
): void {
  const session_token = requireSession();
  const url = `${getApiBase()}/api/chat/text/stream`;
  let buffer = "";
  let settled = false;

  const fail = (err: Error) => {
    if (settled) return;
    settled = true;
    handlers.onError(err);
  };

  const consumeLine = (line: string) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    let obj: any;
    try {
      obj = JSON.parse(trimmed);
    } catch {
      return;
    }
    if (obj.type === "delta" && obj.text) {
      handlers.onDelta(String(obj.text));
      return;
    }
    if (obj.type === "done") {
      if (!settled) {
        settled = true;
        handlers.onDone(obj);
      }
      return;
    }
    if (obj.type === "error" || obj.error) {
      fail(
        new ApiError(String(obj.detail || obj.error || "stream_failed"), {
          code: String(obj.error || "stream_failed"),
          detail: String(obj.detail || obj.error || ""),
          body: obj,
        })
      );
    }
  };

  const appendChunk = (chunk: ArrayBuffer | string) => {
    let piece = "";
    if (typeof chunk === "string") {
      piece = chunk;
    } else {
      try {
        const bytes = new Uint8Array(chunk as ArrayBuffer);
        let s = "";
        for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
        piece = decodeURIComponent(escape(s));
      } catch {
        return;
      }
    }
    buffer += piece;
    const parts = buffer.split("\n");
    buffer = parts.pop() || "";
    parts.forEach(consumeLine);
  };

  const task = uni.request({
    url,
    method: "POST",
    data: { session_token, companion_id, text },
    enableChunked: true,
    success: (res) => {
      if (settled) return;
      const body: any = res.data;
      if (typeof body === "string") {
        appendChunk(body);
        if (buffer.trim()) consumeLine(buffer);
        buffer = "";
        return;
      }
      if (res.statusCode === 402 || body?.error === "quota_exhausted") {
        fail(
          new ApiError(String(body?.detail || "quota_exhausted"), {
            code: "quota_exhausted",
            statusCode: Number(res.statusCode || 402),
            detail: String(body?.detail || ""),
            body: body && typeof body === "object" ? body : {},
          })
        );
        return;
      }
      if (res.statusCode >= 400) {
        const errorMsg = body?.error || `请求失败: ${res.statusCode}`;
        handleSessionError(String(errorMsg));
        fail(
          new ApiError(String(body?.detail || errorMsg), {
            code: String(errorMsg),
            statusCode: Number(res.statusCode || 0),
            detail: String(body?.detail || errorMsg),
            body: body && typeof body === "object" ? body : {},
          })
        );
      }
    },
    fail: (error) => fail(new Error(error.errMsg || "请求失败")),
  }) as UniApp.RequestTask;

  // @ts-expect-error onChunkReceived is WeChat / newer uni
  if (task && typeof task.onChunkReceived === "function") {
    // @ts-expect-error
    task.onChunkReceived((res: { data: ArrayBuffer }) => {
      if (res?.data) appendChunk(res.data);
    });
  }
}

export async function fetchEngagement(companion_id?: string) {
  const session_token = requireSession();
  return request("/api/companions/engagement", {
    method: "POST",
    data: { session_token, companion_id: companion_id || "" },
  });
}

export async function ackCare(care_key: string, companion_id?: string) {
  const session_token = requireSession();
  return request("/api/companions/engagement/ack-care", {
    method: "POST",
    data: {
      session_token,
      care_key,
      companion_id: companion_id || "",
    },
  });
}
