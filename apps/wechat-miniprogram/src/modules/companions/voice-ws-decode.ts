/**
 * WS 下行帧解析（可单测）：区分 JSON 文本与二进制 mp3。
 * 微信偶发把文本帧打成 ArrayBuffer，须先探测 UTF-8 JSON。
 */

export function tryDecodeUtf8JsonText(raw: unknown): string | null {
  if (typeof raw === "string") {
    const s = raw.trimStart();
    return s.startsWith("{") ? raw : null;
  }
  let buffer: ArrayBuffer | null = null;
  if (raw instanceof ArrayBuffer) {
    buffer = raw;
  } else if (typeof ArrayBuffer !== "undefined" && ArrayBuffer.isView && ArrayBuffer.isView(raw as ArrayBufferView)) {
    const view = raw as ArrayBufferView;
    buffer = view.buffer.slice(view.byteOffset, view.byteOffset + view.byteLength);
  }
  if (!buffer || buffer.byteLength < 2) return null;
  const bytes = new Uint8Array(buffer);
  // skip UTF-8 BOM
  let i = 0;
  if (bytes.length >= 3 && bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) i = 3;
  while (i < bytes.length && (bytes[i] === 0x20 || bytes[i] === 0x0a || bytes[i] === 0x0d || bytes[i] === 0x09)) {
    i += 1;
  }
  if (i >= bytes.length || bytes[i] !== 0x7b) return null; // '{'
  try {
    const text = typeof TextDecoder !== "undefined"
      ? new TextDecoder("utf-8").decode(bytes)
      : String.fromCharCode(...Array.from(bytes));
    JSON.parse(text);
    return text;
  } catch {
    return null;
  }
}

export function coerceBinaryFrame(raw: unknown): ArrayBuffer | null {
  if (tryDecodeUtf8JsonText(raw)) return null;
  if (!raw) return null;
  if (raw instanceof ArrayBuffer) return raw;
  if (typeof ArrayBuffer !== "undefined" && ArrayBuffer.isView && ArrayBuffer.isView(raw as ArrayBufferView)) {
    const view = raw as ArrayBufferView;
    return view.buffer.slice(view.byteOffset, view.byteOffset + view.byteLength);
  }
  if (typeof raw === "string" && raw.length > 0 && !raw.trimStart().startsWith("{")) {
    try {
      if (typeof uni !== "undefined" && uni.base64ToArrayBuffer) {
        return uni.base64ToArrayBuffer(raw);
      }
      const chars = (globalThis as any).atob ? (globalThis as any).atob(raw) : "";
      const bytes = new Uint8Array(chars.length);
      for (let i = 0; i < chars.length; i++) bytes[i] = chars.charCodeAt(i);
      return bytes.buffer;
    } catch {
      return null;
    }
  }
  return null;
}

/** 首轮开麦状态机：ready 时 recorder 未就绪须 pending，setup 后补发。 */
export type ListenGateState = {
  ready: boolean;
  hasRecorder: boolean;
  listening: boolean;
  playing: boolean;
  sessionTtsActive: boolean;
  pendingListen: boolean;
};

export function requestStartListen(state: ListenGateState): {
  state: ListenGateState;
  emitListenStart: boolean;
} {
  if (state.listening || state.playing || state.sessionTtsActive) {
    return { state, emitListenStart: false };
  }
  if (!state.ready) {
    return { state: { ...state, pendingListen: true }, emitListenStart: false };
  }
  if (!state.hasRecorder) {
    return { state: { ...state, pendingListen: true }, emitListenStart: false };
  }
  return {
    state: {
      ...state,
      listening: true,
      pendingListen: false,
    },
    emitListenStart: true,
  };
}

export function afterRecorderReady(state: ListenGateState): {
  state: ListenGateState;
  emitListenStart: boolean;
} {
  const next = { ...state, hasRecorder: true };
  if (!next.pendingListen) {
    return { state: next, emitListenStart: false };
  }
  return requestStartListen(next);
}
