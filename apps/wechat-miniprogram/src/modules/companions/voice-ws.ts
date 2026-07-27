/**
 * 小程序软设备 Voice WebSocket：PCM 上行 / 分句 mp3 下行。
 * continuous 模式：sentence_final 由服务端出轮；播音时关麦，播完再听。
 */
const API_BASE = import.meta.env.VITE_SHUXIN_API_BASE || "http://localhost:8765";

function wsBaseFromHttp(httpBase: string): string {
  if (httpBase.startsWith("https://")) return "wss://" + httpBase.slice("https://".length);
  if (httpBase.startsWith("http://")) return "ws://" + httpBase.slice("http://".length);
  return httpBase;
}

export type SoftVoiceHandlers = {
  onStt?: (text: string, state: string) => void;
  onDelta?: (text: string) => void;
  onReply?: (text: string) => void;
  onThinking?: () => void;
  onTtsIdle?: () => void;
  onError?: (message: string) => void;
  onReady?: () => void;
  onBusy?: (busy: boolean) => void;
};

type PlayItem = { path: string };

export class SoftVoiceSession {
  private socketTask: UniApp.SocketTask | null = null;
  private ready = false;
  private listening = false;
  private recorder: UniApp.RecorderManager | null = null;
  private sentenceChunks: ArrayBuffer[] = [];
  private playQueue: PlayItem[] = [];
  private playing = false;
  private sessionTtsActive = false;
  private autoResumeListen = false;
  private conversationMode: "push_to_talk" | "continuous" = "push_to_talk";
  private handlers: SoftVoiceHandlers;
  private deviceId: string;
  private deviceSecret: string;
  private companionId: string;
  private currentAudio: UniApp.InnerAudioContext | null = null;
  /** 有未确认错误时，tts idle 不要盖成「请继续说」 */
  private stickyError = false;

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

  async connect(opts?: { conversationMode?: "push_to_talk" | "continuous" }): Promise<void> {
    if (this.socketTask) return;
    this.conversationMode = opts?.conversationMode || "push_to_talk";
    this.autoResumeListen = this.conversationMode === "continuous";
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
            conversation_mode: this.conversationMode,
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
      setTimeout(() => {
        if (!this.ready) reject(new Error("voice hello timeout"));
      }, 8000);
    });
    this.setupRecorder();
  }

  private handleMessage(raw: string | ArrayBuffer) {
    if (typeof raw !== "string") {
      this.sentenceChunks.push(raw as ArrayBuffer);
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
      if (data.text) this.handlers.onStt?.(String(data.text), String(data.state));
      if (data.state === "sentence_final" && this.conversationMode === "continuous") {
        this.stopRecorderOnly();
      }
      return;
    }
    if (t === "agent" && data.state === "thinking") {
      this.stopRecorderOnly();
      this.handlers.onThinking?.();
      this.handlers.onBusy?.(true);
      return;
    }
    if (t === "agent" && data.state === "delta" && data.text) {
      this.stickyError = false;
      this.handlers.onDelta?.(String(data.text));
      return;
    }
    if (t === "agent" && data.state === "reply") {
      this.stickyError = false;
      this.handlers.onReply?.(String(data.text || ""));
      return;
    }
    if (t === "tts" && data.state === "sentence_start") {
      this.sentenceChunks = [];
      this.sessionTtsActive = true;
      this.handlers.onBusy?.(true);
      this.stopRecorderOnly();
      return;
    }
    if (t === "tts" && data.state === "sentence_stop") {
      if (data.error_kind) {
        this.stickyError = true;
        this.handlers.onError?.(String(data.message || data.error_kind || "tts_failed"));
      }
      void this.enqueueSentenceMp3();
      return;
    }
    if (t === "tts" && data.state === "start") {
      this.sentenceChunks = [];
      this.sessionTtsActive = true;
      this.handlers.onBusy?.(true);
      this.stopRecorderOnly();
      return;
    }
    if (t === "tts" && data.state === "stop") {
      this.sessionTtsActive = false;
      // 若还有句缓冲（兼容整段下发），入队
      if (this.sentenceChunks.length) {
        void this.enqueueSentenceMp3().then(() => this.maybeResumeAfterTts());
      } else {
        this.maybeResumeAfterTts();
      }
      return;
    }
    if (t === "error" || (t === "agent" && data.state === "error")) {
      this.stickyError = true;
      this.handlers.onError?.(String(data.message || data.error_kind || "voice error"));
      this.handlers.onBusy?.(false);
      this.sessionTtsActive = false;
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
    if (!this.ready || !this.recorder || this.listening || this.playing || this.sessionTtsActive) {
      return;
    }
    this.listening = true;
    this.sentenceChunks = [];
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

  private stopRecorderOnly() {
    if (!this.listening) return;
    this.listening = false;
    try {
      this.recorder?.stop();
    } catch {
      /* ignore */
    }
  }

  private async enqueueSentenceMp3() {
    if (!this.sentenceChunks.length) return;
    const chunks = this.sentenceChunks;
    this.sentenceChunks = [];
    try {
      const total = chunks.reduce((n, b) => n + b.byteLength, 0);
      const merged = new Uint8Array(total);
      let offset = 0;
      for (const chunk of chunks) {
        merged.set(new Uint8Array(chunk), offset);
        offset += chunk.byteLength;
      }
      const fs = uni.getFileSystemManager();
      const userDataPath =
        (typeof wx !== "undefined" && (wx as any).env && (wx as any).env.USER_DATA_PATH) ||
        `${uni.env.USER_DATA_PATH || ""}`;
      const path = `${userDataPath}/soft-tts-${Date.now()}-${Math.random().toString(16).slice(2)}.mp3`;
      fs.writeFileSync(path, merged.buffer as any, "binary");
      this.playQueue.push({ path });
      void this.pumpPlayQueue();
    } catch (e: any) {
      this.handlers.onError?.(e?.message || "播放失败");
    }
  }

  private async pumpPlayQueue() {
    if (this.playing) return;
    const next = this.playQueue.shift();
    if (!next) {
      this.maybeResumeAfterTts();
      return;
    }
    this.playing = true;
    this.handlers.onBusy?.(true);
    await new Promise<void>((resolve) => {
      try {
        const audio = uni.createInnerAudioContext();
        this.currentAudio = audio;
        audio.src = next.path;
        audio.obeyMuteSwitch = false;
        audio.autoplay = true;
        const done = () => {
          try {
            audio.destroy();
          } catch {
            /* ignore */
          }
          if (this.currentAudio === audio) this.currentAudio = null;
          resolve();
        };
        audio.onEnded(done);
        audio.onError(() => {
          this.handlers.onError?.("播放失败");
          done();
        });
        try {
          audio.play();
        } catch {
          done();
        }
      } catch {
        resolve();
      }
    });
    this.playing = false;
    void this.pumpPlayQueue();
  }

  private maybeResumeAfterTts() {
    if (this.sessionTtsActive || this.playing || this.playQueue.length) return;
    this.handlers.onBusy?.(false);
    if (!this.stickyError) {
      this.handlers.onTtsIdle?.();
    }
    if (this.autoResumeListen && this.ready) {
      this.startListen();
    }
  }

  close() {
    this.autoResumeListen = false;
    this.sessionTtsActive = false;
    this.playQueue = [];
    try {
      this.currentAudio?.stop();
      this.currentAudio?.destroy();
    } catch {
      /* ignore */
    }
    this.currentAudio = null;
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
