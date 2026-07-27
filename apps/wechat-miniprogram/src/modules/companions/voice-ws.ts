/**
 * 小程序软设备 Voice WebSocket：PCM 上行 / 分句 mp3 下行。
 * continuous 模式：sentence_final 由服务端出轮；播音时关麦，播完再听。
 * 协议对齐 /voice-demo：hello.ok 后才可 listen；agent/delta 文字流 + 分句 mp3。
 */
import {
  afterRecorderReady,
  coerceBinaryFrame,
  requestStartListen,
  tryDecodeUtf8JsonText,
  type ListenGateState,
} from "./voice-ws-decode";

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
  private forceRelistenPending = false;
  /** ready 时 recorder 未就绪 / 暂不可听，补发 startListen */
  private pendingListen = false;

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
    // 必须在等 hello.ok / onReady→startListen 之前就绪，否则首轮静默丢麦
    this.setupRecorder();
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
    if (this.pendingListen) {
      this.startListen();
    }
  }

  private listenGateSnapshot(): ListenGateState {
    return {
      ready: this.ready,
      hasRecorder: !!this.recorder,
      listening: this.listening,
      playing: this.playing,
      sessionTtsActive: this.sessionTtsActive,
      pendingListen: this.pendingListen,
    };
  }

  private applyListenGate(next: ListenGateState, emitListenStart: boolean) {
    this.pendingListen = next.pendingListen;
    if (!emitListenStart) return;
    this.listening = true;
    this.forceRelistenPending = false;
    this.sentenceChunks = [];
    this.handlers.onBusy?.(true);
    this.socketTask?.send({ data: JSON.stringify({ type: "listen", state: "start" }) });
    this.recorder?.start({
      format: "PCM",
      sampleRate: 16000,
      numberOfChannels: 1,
      frameSize: 4,
      // @ts-expect-error uni types vary by platform
      encodeBitRate: 48000,
    });
  }

  private handleMessage(raw: unknown) {
    const jsonText = tryDecodeUtf8JsonText(raw);
    if (jsonText != null) {
      this.handleJsonMessage(jsonText);
      return;
    }
    const binary = coerceBinaryFrame(raw);
    if (binary) {
      this.sentenceChunks.push(binary);
      return;
    }
  }

  private handleJsonMessage(raw: string) {
    let data: any;
    try {
      data = JSON.parse(raw);
    } catch {
      return;
    }
    const t = data.type;
    // 仅鉴权成功后的 hello.ok 才允许录音；hello.ready 只表示 socket 已建立
    if (t === "hello" && data.state === "ok") {
      this.ready = true;
      this.handlers.onReady?.();
      if (this.pendingListen) this.startListen();
      return;
    }
    if (t === "hello" && data.state === "ready") {
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
      void this.enqueueSentenceMp3(Boolean(data.error_kind));
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
      this.forceRelistenPending = this.autoResumeListen;
      if (this.sentenceChunks.length) {
        void this.enqueueSentenceMp3().then(() => this.maybeResumeAfterTts());
      } else {
        this.maybeResumeAfterTts();
      }
      return;
    }
    if (t === "error" || (t === "agent" && data.state === "error")) {
      const kind = String(data.error_kind || "");
      const msg = String(data.message || data.error_kind || "voice error");
      if (kind === "tts_failed") {
        this.handlers.onError?.(msg);
      } else {
        this.stickyError = true;
        this.handlers.onError?.(msg);
        this.sessionTtsActive = false;
      }
      this.handlers.onBusy?.(false);
    }
  }

  private setupRecorder() {
    if (this.recorder) return;
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
    const { state, emitListenStart } = afterRecorderReady(this.listenGateSnapshot());
    this.applyListenGate(state, emitListenStart);
  }

  startListen() {
    const { state, emitListenStart } = requestStartListen(this.listenGateSnapshot());
    this.applyListenGate(state, emitListenStart);
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

  private async enqueueSentenceMp3(allowEmpty = false) {
    if (!this.sentenceChunks.length) {
      if (!allowEmpty) {
        this.stickyError = true;
        this.handlers.onError?.("tts_audio_missing");
      }
      return;
    }
    const chunks = this.sentenceChunks;
    this.sentenceChunks = [];
    try {
      const total = chunks.reduce((n, b) => n + b.byteLength, 0);
      if (total <= 0) {
        this.stickyError = true;
        this.handlers.onError?.("tts_audio_missing");
        return;
      }
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
      this.stickyError = true;
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
          this.stickyError = true;
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
    if ((this.autoResumeListen || this.forceRelistenPending) && this.ready) {
      this.forceRelistenPending = false;
      setTimeout(() => this.startListen(), 50);
    }
  }

  close() {
    this.autoResumeListen = false;
    this.forceRelistenPending = false;
    this.pendingListen = false;
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
