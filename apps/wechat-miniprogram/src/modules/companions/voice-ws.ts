/**
 * 小程序软设备 Voice WebSocket 客户端（PCM 上行 / mp3 下行，对齐 web-demo）。
 */
const API_BASE = import.meta.env.VITE_SHUXIN_API_BASE || "http://localhost:8765";

function wsBaseFromHttp(httpBase: string): string {
  if (httpBase.startsWith("https://")) return "wss://" + httpBase.slice("https://".length);
  if (httpBase.startsWith("http://")) return "ws://" + httpBase.slice("http://".length);
  return httpBase;
}

export type SoftVoiceHandlers = {
  onStt?: (text: string) => void;
  onDelta?: (text: string) => void;
  onReply?: (text: string) => void;
  onError?: (message: string) => void;
  onReady?: () => void;
  onBusy?: (busy: boolean) => void;
};

export class SoftVoiceSession {
  private socketTask: UniApp.SocketTask | null = null;
  private ready = false;
  private listening = false;
  private recorder: UniApp.RecorderManager | null = null;
  private mp3Chunks: ArrayBuffer[] = [];
  private handlers: SoftVoiceHandlers;
  private deviceId: string;
  private deviceSecret: string;
  private companionId: string;

  constructor(
    creds: { device_id: string; device_secret: string },
    companionId: string,
    handlers: SoftVoiceHandlers = {}
  ) {
    this.deviceId = creds.device_id;
    this.deviceSecret = creds.device_secret;
    this.companionId = companionId;
    this.handlers = handlers;
  }

  async connect(): Promise<void> {
    if (this.socketTask) return;
    const url = `${wsBaseFromHttp(API_BASE.replace(/\/$/, ""))}/ws/voice`;
    await new Promise<void>((resolve, reject) => {
      const task = uni.connectSocket({
        url,
        fail: (err) => reject(new Error(err.errMsg || "ws connect failed")),
      });
      this.socketTask = task;
      task.onOpen(() => {
        task.send({
          data: JSON.stringify({
            type: "hello",
            device_code: this.deviceId,
            device_secret: this.deviceSecret,
            client_id: "soft-miniprogram",
            companion_id: this.companionId,
            audio_params: { format: "pcm", sample_rate: 16000, channels: 1 },
          }),
        });
      });
      task.onError((err) => {
        this.handlers.onError?.(err.errMsg || "ws error");
        reject(new Error(err.errMsg || "ws error"));
      });
      task.onMessage((msg) => {
        this.handleMessage(msg.data);
        if (this.ready) resolve();
      });
      // 超时保护
      setTimeout(() => {
        if (!this.ready) reject(new Error("voice hello timeout"));
      }, 8000);
    });
    this.setupRecorder();
  }

  private handleMessage(raw: string | ArrayBuffer) {
    if (typeof raw !== "string") {
      // mp3 binary chunk
      this.mp3Chunks.push(raw as ArrayBuffer);
      return;
    }
    let data: any;
    try {
      data = JSON.parse(raw);
    } catch {
      return;
    }
    const t = data.type;
    if (t === "hello" && (data.state === "ok" || data.state === "ready")) {
      this.ready = true;
      this.handlers.onReady?.();
      return;
    }
    if (t === "stt" && ["partial", "final", "sentence_final", "stream_final"].includes(data.state)) {
      if (data.text) this.handlers.onStt?.(String(data.text));
      return;
    }
    if (t === "agent" && data.state === "delta" && data.text) {
      this.handlers.onDelta?.(String(data.text));
      return;
    }
    if (t === "agent" && data.state === "reply" && data.text) {
      this.handlers.onReply?.(String(data.text));
      return;
    }
    if (t === "tts" && data.state === "start") {
      this.mp3Chunks = [];
      this.handlers.onBusy?.(true);
      return;
    }
    if (t === "tts" && data.state === "stop") {
      this.handlers.onBusy?.(false);
      void this.playCollectedMp3();
      return;
    }
    if (t === "error" || (t === "agent" && data.state === "error")) {
      this.handlers.onError?.(String(data.message || data.error_kind || "voice error"));
      this.handlers.onBusy?.(false);
    }
  }

  private setupRecorder() {
    const rec = uni.getRecorderManager();
    this.recorder = rec;
    rec.onFrameRecorded((res) => {
      if (!this.listening || !this.socketTask || !res.frameBuffer) return;
      this.socketTask.send({ data: res.frameBuffer });
    });
    rec.onError((err) => {
      this.handlers.onError?.(err.errMsg || "recorder error");
      this.listening = false;
      this.handlers.onBusy?.(false);
    });
  }

  startListen() {
    if (!this.ready || !this.recorder || this.listening) return;
    this.listening = true;
    this.mp3Chunks = [];
    this.handlers.onBusy?.(true);
    this.socketTask?.send({ data: JSON.stringify({ type: "listen", state: "start" }) });
    this.recorder.start({
      format: "PCM",
      sampleRate: 16000,
      numberOfChannels: 1,
      frameSize: 4,
      // @ts-expect-error uni types vary by platform
      encodeBitRate: 48000,
    });
  }

  stopListen() {
    if (!this.listening) return;
    this.listening = false;
    try {
      this.recorder?.stop();
    } catch {
      /* ignore */
    }
    this.socketTask?.send({ data: JSON.stringify({ type: "listen", state: "stop" }) });
  }

  private async playCollectedMp3() {
    if (!this.mp3Chunks.length) return;
    try {
      const total = this.mp3Chunks.reduce((n, b) => n + b.byteLength, 0);
      const merged = new Uint8Array(total);
      let offset = 0;
      for (const chunk of this.mp3Chunks) {
        merged.set(new Uint8Array(chunk), offset);
        offset += chunk.byteLength;
      }
      const fs = uni.getFileSystemManager();
      const userDataPath =
        (typeof wx !== "undefined" && (wx as any).env && (wx as any).env.USER_DATA_PATH) ||
        `${uni.env.USER_DATA_PATH || ""}`;
      const path = `${userDataPath}/soft-tts-${Date.now()}.mp3`;
      fs.writeFileSync(path, merged.buffer as any, "binary");
      const audio = uni.createInnerAudioContext();
      audio.src = path;
      audio.autoplay = true;
      audio.onEnded(() => audio.destroy());
      audio.onError(() => audio.destroy());
    } catch (e: any) {
      this.handlers.onError?.(e?.message || "播放失败");
    } finally {
      this.mp3Chunks = [];
    }
  }

  close() {
    try {
      this.recorder?.stop();
    } catch {
      /* ignore */
    }
    this.socketTask?.close({});
    this.socketTask = null;
    this.ready = false;
    this.listening = false;
  }
}
