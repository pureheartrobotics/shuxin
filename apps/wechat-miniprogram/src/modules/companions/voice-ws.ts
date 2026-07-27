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
  /** 仅在真正 start 成功后为 true；未启动时禁止 stop，否则微信报 recorder not start */
  private recorderStarted = false;

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
    // iOS 静音键下仍可播 TTS
    try {
      if (typeof wx !== "undefined" && (wx as any).setInnerAudioOption) {
        (wx as any).setInnerAudioOption({ obeyMuteSwitch: false, mixWithOther: true });
      }
    } catch {
      /* ignore */
    }
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
    // 仅当上一轮确实在录时才 stop；未 start 就 stop → operateRecorder:fail recorder not start
    const needStopGap = this.recorderStarted;
    if (needStopGap) {
      this.safeStopRecorder();
    }
    this.socketTask?.send({ data: JSON.stringify({ type: "listen", state: "start" }) });
    const startRec = () => {
      if (!this.listening || !this.recorder) return;
      try {
        this.recorder.start({
          format: "PCM",
          sampleRate: 16000,
          numberOfChannels: 1,
          frameSize: 4,
          // @ts-expect-error uni types vary by platform
          encodeBitRate: 48000,
        });
        this.recorderStarted = true;
      } catch (e: any) {
        this.recorderStarted = false;
        this.stickyError = true;
        this.handlers.onError?.(e?.errMsg || e?.message || "recorder start failed");
        this.listening = false;
      }
    };
    setTimeout(startRec, needStopGap ? 40 : 0);
  }

  private safeStopRecorder() {
    if (!this.recorderStarted || !this.recorder) {
      this.recorderStarted = false;
      return;
    }
    try {
      this.recorder.stop();
    } catch {
      /* ignore */
    }
    this.recorderStarted = false;
  }

  private handleMessage(raw: unknown) {
    // 微信下行：文本 JSON 与 mp3 二进制可能是 string / ArrayBuffer / TypedArray
    const jsonText = tryDecodeUtf8JsonText(raw);
    if (jsonText != null) {
      this.handleJsonMessage(jsonText);
      return;
    }
    const binary = coerceBinaryFrame(raw);
    if (binary && binary.byteLength > 0) {
      this.sentenceChunks.push(binary);
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
        void this.enqueueSentenceMp3(true);
        return;
      }
      // 括弧动作句：服务端 skipped/无音频，勿报 tts_audio_missing
      const skipped =
        data.skipped === true ||
        data.speakable === false ||
        this.sentenceChunks.length === 0;
      void this.enqueueSentenceMp3(skipped);
      return;
    }
    if (t === "tts" && data.state === "start") {
      // 会话级 start：只标记播音中，不要清空句缓冲（避免与首包二进制竞态）
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
      const buf =
        res.frameBuffer instanceof ArrayBuffer
          ? res.frameBuffer
          : ArrayBuffer.isView(res.frameBuffer as any)
            ? (res.frameBuffer as ArrayBufferView).buffer.slice(
                (res.frameBuffer as ArrayBufferView).byteOffset,
                (res.frameBuffer as ArrayBufferView).byteOffset +
                  (res.frameBuffer as ArrayBufferView).byteLength
              )
            : null;
      if (!buf || buf.byteLength <= 0) return;
      this.socketTask.send({ data: buf as any });
    });
    rec.onError((err) => {
      const msg = String(err.errMsg || "recorder error");
      this.recorderStarted = false;
      // 未 start 就 stop 的噪声：不打断即将进行的 start、不 sticky
      if (/recorder not start/i.test(msg)) {
        return;
      }
      this.handlers.onError?.(msg);
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
    this.safeStopRecorder();
    this.socketTask?.send({ data: JSON.stringify({ type: "listen", state: "stop" }) });
  }

  private stopRecorderOnly() {
    if (!this.listening) return;
    this.listening = false;
    this.safeStopRecorder();
  }

  private async enqueueSentenceMp3(allowEmpty = false) {
    const chunkCount = this.sentenceChunks.length;
    if (!chunkCount) {
      if (!allowEmpty) {
        this.stickyError = true;
        this.handlers.onError?.("tts_audio_missing chunks=0");
      }
      return;
    }
    const chunks = this.sentenceChunks;
    this.sentenceChunks = [];
    try {
      const total = chunks.reduce((n, b) => n + b.byteLength, 0);
      if (total <= 0) {
        this.stickyError = true;
        this.handlers.onError?.(`tts_audio_missing chunks=${chunkCount} bytes=0`);
        return;
      }
      const merged = new Uint8Array(total);
      let offset = 0;
      for (const chunk of chunks) {
        merged.set(new Uint8Array(chunk), offset);
        offset += chunk.byteLength;
      }
      const exact = merged.buffer.slice(merged.byteOffset, merged.byteOffset + merged.byteLength);
      const fs = uni.getFileSystemManager();
      const userDataPath =
        (typeof wx !== "undefined" && (wx as any).env && (wx as any).env.USER_DATA_PATH) ||
        (uni as any).env?.USER_DATA_PATH ||
        "";
      if (!userDataPath) {
        this.stickyError = true;
        this.handlers.onError?.("tts_write_failed no USER_DATA_PATH");
        return;
      }
      const path = `${userDataPath}/soft-tts-${Date.now()}-${Math.random().toString(16).slice(2)}.mp3`;
      // 微信：ArrayBuffer 直接写盘最稳；base64 作兜底
      try {
        fs.writeFileSync(path, exact as any);
      } catch {
        const b64 = uni.arrayBufferToBase64
          ? uni.arrayBufferToBase64(exact)
          : "";
        if (!b64) {
          this.stickyError = true;
          this.handlers.onError?.(`tts_write_failed bytes=${total}`);
          return;
        }
        fs.writeFileSync(path, b64, "base64");
      }
      try {
        const info = fs.statSync ? fs.statSync(path) : null;
        const size = info && typeof (info as any).size === "number" ? (info as any).size : total;
        if (!size || size <= 0) {
          this.stickyError = true;
          this.handlers.onError?.("tts_write_failed empty_file");
          return;
        }
      } catch {
        // stat 不可用时仍尝试播放
      }
      this.playQueue.push({ path });
      void this.pumpPlayQueue();
    } catch (e: any) {
      this.stickyError = true;
      this.handlers.onError?.(e?.errMsg || e?.message || "tts_write_failed");
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
      let audio: UniApp.InnerAudioContext | null = null;
      let settled = false;
      let playRequested = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        if (audio) {
          try {
            audio.destroy();
          } catch {
            /* ignore */
          }
        }
        if (this.currentAudio === audio) this.currentAudio = null;
        resolve();
      };
      const tryPlay = () => {
        if (settled || !audio || playRequested) return;
        playRequested = true;
        try {
          audio.play();
        } catch (e: any) {
          this.stickyError = true;
          this.handlers.onError?.(e?.errMsg || e?.message || "播放失败 play()");
          finish();
        }
      };
      try {
        audio = uni.createInnerAudioContext();
        this.currentAudio = audio;
        audio.obeyMuteSwitch = false;
        // @ts-expect-error volume exists on WeChat InnerAudioContext
        audio.volume = 1;
        audio.autoplay = false;
        audio.onEnded(finish);
        audio.onStop(finish);
        audio.onError((err: any) => {
          this.stickyError = true;
          const detail = err?.errMsg || err?.errCode || JSON.stringify(err) || "unknown";
          this.handlers.onError?.(`播放失败 ${detail}`);
          finish();
        });
        audio.onCanplay(tryPlay);
        audio.src = next.path;
        // 部分基础库不触发 onCanplay，兜底再 play 一次
        setTimeout(tryPlay, 120);
      } catch (e: any) {
        this.stickyError = true;
        this.handlers.onError?.(e?.message || "播放失败 create");
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
    this.safeStopRecorder();
    this.socketTask?.close({});
    this.socketTask = null;
    this.ready = false;
    this.listening = false;
  }
}
