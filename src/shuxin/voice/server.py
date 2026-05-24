from __future__ import annotations

import argparse
import asyncio
import json
import uuid
import time
from pathlib import Path

from shuxin.core.config import get_shuxin_home
from shuxin.voice.config import DeviceConfigProvider
from shuxin.voice.providers import create_stt_provider, create_tts_provider
from shuxin.voice.service import VoiceService
from shuxin.voice.storage import UserVoiceStorage
from shuxin.voice.users import DEFAULT_USER_ID, UserConfigProvider

# WebSocket 上行音频统一按 16kHz / mono / PCM16 处理。
# 浏览器测试台和后续硬件只需要发送裸 PCM 帧，不需要封装 wav 头。
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
CHANNELS = 1


def build_parser() -> argparse.ArgumentParser:
    """构建 voice server 的命令行参数。

    这个入口主要给 Docker 常驻服务和本机无硬件测试使用。
    """
    parser = argparse.ArgumentParser(description="ShuXin voice WebSocket demo server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--device-config", default=None)
    parser.add_argument("--users-config", default=None)
    parser.add_argument("--default-device-id", default="demo-device-001")
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/web"))
    return parser


def create_app(
    device_config: str | None = None,
    users_config: str | None = None,
    default_device_id: str = "demo-device-001",
    out_dir: Path = Path("outputs/web"),
):
    """创建 FastAPI 应用，并注册语音测试台相关 HTTP/WebSocket 入口。

    主要职责:
    1. 暴露浏览器测试页和健康检查接口。
    2. 提供用户语音状态/摘要查询接口。
    3. 通过 `/ws/voice` 承接准实时语音对话。
    """
    try:
        from fastapi import FastAPI, WebSocket, WebSocketDisconnect
        from fastapi.responses import HTMLResponse, JSONResponse
    except ImportError as exc:
        raise RuntimeError(
            "FastAPI is not installed. Add voice web dependencies and rebuild Docker."
        ) from exc
    globals()["WebSocket"] = WebSocket

    app = FastAPI(title="ShuXin Voice Demo")
    service = VoiceService(DeviceConfigProvider(device_config))
    user_provider = UserConfigProvider(users_config)
    shuxin_home = get_shuxin_home()
    out_dir.mkdir(parents=True, exist_ok=True)

    @app.get("/health")
    async def health():
        return JSONResponse({"status": "ok", "service": "shuxin-voice-demo"})

    @app.get("/voice-demo")
    async def voice_demo():
        return HTMLResponse(_web_demo_html(default_device_id))

    @app.get("/voice/status")
    async def voice_status(user_id: str = DEFAULT_USER_ID, token: str = ""):
        try:
            settings = user_provider.authenticate(user_id, token)
            storage = UserVoiceStorage(shuxin_home, out_dir, settings.user_id)
            return JSONResponse(await storage.status(settings))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)

    @app.get("/voice/export")
    async def voice_export(user_id: str = DEFAULT_USER_ID, token: str = ""):
        try:
            settings = user_provider.authenticate(user_id, token)
            storage = UserVoiceStorage(shuxin_home, out_dir, settings.user_id)
            return JSONResponse(
                {
                    "user_id": settings.user_id,
                    "shared_memory": storage.export_summary(),
                    "include_audio": False,
                }
            )
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)

    @app.websocket("/ws/voice")
    async def voice_ws(websocket: WebSocket):
        await websocket.accept()
        session = _VoiceWebSocketSession(
            websocket=websocket,
            service=service,
            user_provider=user_provider,
            shuxin_home=shuxin_home,
            default_device_id=default_device_id,
            out_dir=out_dir,
        )
        try:
            await session.run()
        except WebSocketDisconnect:
            await session.shutdown()

    return app


class _VoiceWebSocketSession:
    """单条 WebSocket 连接的运行态。

    一个连接会绑定 user_id、device_id、client_id 和 session_id。
    同一个用户的多台设备共享长期记忆目录，但每轮音频附件仍按
    user/device/session 分层保存，方便后续做额度控制和事件回放。
    """

    def __init__(
        self,
        websocket,
        service: VoiceService,
        user_provider: UserConfigProvider,
        shuxin_home: Path,
        default_device_id: str,
        out_dir: Path,
    ):
        self.websocket = websocket
        self.service = service
        self.user_provider = user_provider
        self.shuxin_home = shuxin_home
        self.default_device_id = default_device_id
        self.out_dir = out_dir
        self.user_id = DEFAULT_USER_ID
        self.user_settings = None
        self.storage: UserVoiceStorage | None = None
        self.session_id = ""
        self.device_id = default_device_id
        self.client_id = "web-demo"
        self.device = None
        self.stt = None
        self.tts = None
        self.agent = None
        self.audio_chunks: list[bytes] = []
        self.listening = False

    async def run(self) -> None:
        """进入消息循环，按文本控制消息和二进制音频帧分流处理。"""
        await self._send_json(
            {"type": "hello", "state": "ready", "device_id": self.device_id}
        )

        while True:
            message = await self.websocket.receive()
            if "text" in message:
                await self._handle_text(message["text"])
            elif "bytes" in message:
                await self._handle_audio_frame(message["bytes"])

    async def shutdown(self) -> None:
        """关闭连接时释放当前 Agent，避免插件状态和资源泄漏。"""
        if self.agent is not None:
            await asyncio.to_thread(self.agent.shutdown)
            self.agent = None

    async def _handle_text(self, raw: str) -> None:
        """处理设备/浏览器上行的 JSON 控制消息。

        `hello` 决定用户身份和设备配置；`listen start/stop` 决定一轮
        语音采集边界；`abort` 清空当前轮缓存；`ping` 用于连接保活。
        """
        data = json.loads(raw)
        message_type = data.get("type")

        if message_type == "hello":
            try:
                self.user_settings = self.user_provider.authenticate(
                    data.get("user_id") or DEFAULT_USER_ID,
                    data.get("token") or "",
                )
            except Exception as exc:
                await self._send_json({"type": "error", "message": str(exc)})
                return
            self.user_id = self.user_settings.user_id
            self.device_id = data.get("device_id") or self.default_device_id
            self.client_id = data.get("client_id") or "web-demo"
            self.storage = UserVoiceStorage(self.shuxin_home, self.out_dir, self.user_id)
            self.session_id = data.get("session_id") or uuid.uuid4().hex
            await self._reset_runtime()
            await self._send_json(
                {
                    "type": "hello",
                    "state": "ok",
                    "user_id": self.user_id,
                    "device_id": self.device_id,
                    "client_id": self.client_id,
                    "session_id": self.session_id,
                }
            )
            return

        if message_type == "listen" and data.get("state") == "start":
            self.audio_chunks = []
            self.listening = True
            await self._send_json({"type": "listen", "state": "start"})
            return

        if message_type == "listen" and data.get("state") == "stop":
            self.listening = False
            await self._process_turn()
            return

        if message_type == "abort":
            self.audio_chunks = []
            self.listening = False
            await self._send_json({"type": "abort", "state": "ok"})
            return

        if message_type == "ping":
            await self._send_json({"type": "pong", "ts": time.time()})
            return

        await self._send_json({"type": "error", "message": f"unsupported message: {data}"})

    async def _handle_audio_frame(self, frame: bytes) -> None:
        """缓存 listen 窗口内收到的 PCM16 二进制音频帧。"""
        if self.listening and frame:
            self.audio_chunks.append(frame)

    async def _process_turn(self) -> None:
        """处理完整的一轮语音对话。

        流程是: PCM 帧落盘为 wav -> STT -> Agent 文本回复 -> TTS ->
        mp3 下发 -> 事件和附件索引入库。第一版是 turn-based 准实时，
        即用户松手后才开始识别和回复。
        """
        if not self.audio_chunks:
            await self._send_json({"type": "error", "message": "no audio received"})
            return

        started = time.perf_counter()
        pcm = b"".join(self.audio_chunks)

        try:
            await self._ensure_runtime()
            assert self.storage is not None
            assert self.user_settings is not None
            paths = self.storage.new_turn_paths(self.device_id, self.session_id or None)
            self.session_id = paths.session_id
            self.storage.write_input_wav(pcm, paths.input_wav)
            await self._send_json({"type": "stt", "state": "start"})
            stt_started = time.perf_counter()
            text = await self.stt.transcribe(paths.input_wav)
            stt_ms = _elapsed_ms(stt_started)
            await self._send_json(
                {"type": "stt", "state": "final", "text": text, "elapsed_ms": stt_ms}
            )

            agent_started = time.perf_counter()
            reply = await asyncio.to_thread(self.agent.chat, text)
            reply = reply.strip()
            agent_ms = _elapsed_ms(agent_started)
            await self._send_json(
                {"type": "agent", "state": "reply", "text": reply, "elapsed_ms": agent_ms}
            )

            await self._send_json({"type": "tts", "state": "start"})
            tts_started = time.perf_counter()
            speech_path = await self.tts.synthesize(reply, paths.reply_mp3)
            tts_ms = _elapsed_ms(tts_started)
            await self.websocket.send_bytes(speech_path.read_bytes())
            await self.storage.record_turn(
                user_settings=self.user_settings,
                device_id=self.device_id,
                client_id=self.client_id,
                session_id=self.session_id,
                turn_id=paths.turn_id,
                user_text=text,
                reply_text=reply,
                input_audio=paths.input_wav,
                reply_audio=speech_path,
                timings={
                    "stt_ms": stt_ms,
                    "agent_ms": agent_ms,
                    "tts_ms": tts_ms,
                    "total_elapsed_ms": _elapsed_ms(started),
                },
            )
            asyncio.create_task(self.storage.compress_if_needed(self.user_settings))
            await self._send_json(
                {
                    "type": "tts",
                    "state": "stop",
                    "elapsed_ms": tts_ms,
                    "total_elapsed_ms": _elapsed_ms(started),
                }
            )
        except Exception as exc:
            await self._send_json({"type": "error", "message": str(exc)})
        finally:
            self.audio_chunks = []

    async def _reset_runtime(self) -> None:
        """切换用户或设备时重建运行态，确保配置和记忆目录重新绑定。"""
        await self.shutdown()
        self.stt = None
        self.tts = None
        self.device = None

    async def _ensure_runtime(self) -> None:
        """懒加载设备配置、STT/TTS provider 和按用户隔离的 Agent。"""
        if self.storage is None:
            self.user_settings = self.user_provider.authenticate(DEFAULT_USER_ID, "")
            self.user_id = self.user_settings.user_id
            self.storage = UserVoiceStorage(self.shuxin_home, self.out_dir, self.user_id)
        if self.device is None:
            self.device = self.service.device_provider.get(self.device_id)
            self.stt = create_stt_provider(self.device.stt)
            self.tts = create_tts_provider(self.device.tts)
            self.agent = self.service.create_agent(
                self.device,
                user_home=self.storage.user_shuxin_home(),
            )
            await asyncio.to_thread(self.agent.initialize)

    async def _send_json(self, data: dict) -> None:
        """以 UTF-8 JSON 文本消息下发状态，保留中文错误和回复内容。"""
        await self.websocket.send_text(json.dumps(data, ensure_ascii=False))


def _elapsed_ms(started: float) -> int:
    """把 perf_counter 起点转换为毫秒耗时，便于前端展示链路耗时。"""
    return int((time.perf_counter() - started) * 1000)


def _web_demo_html(default_device_id: str) -> str:
    """返回内嵌浏览器测试台 HTML。

    测试台模拟未来硬件: 按住录音、Web Audio 下采样到 16k PCM16、
    WebSocket 上行音频帧，并播放服务端返回的 mp3。
    """
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ShuXin Voice Demo</title>
  <style>
    body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; background: #f6f7f9; color: #20242a; }}
    main {{ max-width: 880px; margin: 0 auto; padding: 28px 18px 40px; }}
    h1 {{ font-size: 28px; margin: 0 0 18px; }}
    .toolbar {{ display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-bottom: 18px; }}
    input {{ height: 38px; padding: 0 10px; border: 1px solid #cfd6df; border-radius: 6px; min-width: 220px; }}
    button {{ height: 40px; padding: 0 16px; border: 0; border-radius: 6px; background: #1b6ef3; color: white; cursor: pointer; }}
    button:disabled {{ background: #9aa7b6; cursor: not-allowed; }}
    #record {{ background: #d63847; min-width: 160px; }}
    #record.recording {{ background: #9f1d2b; }}
    .panel {{ background: white; border: 1px solid #e1e6ec; border-radius: 8px; padding: 16px; margin-top: 12px; }}
    .row {{ display: grid; grid-template-columns: 120px 1fr; gap: 12px; padding: 7px 0; border-bottom: 1px solid #eef1f4; }}
    .row:last-child {{ border-bottom: 0; }}
    .label {{ color: #657080; }}
    #log {{ white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; max-height: 280px; overflow: auto; }}
  </style>
</head>
<body>
  <main>
    <h1>ShuXin 语音测试台</h1>
    <div class="toolbar">
      <input id="userId" value="demo-user" aria-label="user id" />
      <input id="userToken" value="" aria-label="user token" placeholder="token" />
      <input id="deviceId" value="{default_device_id}" aria-label="device id" />
      <button id="connect">连接</button>
      <button id="record" disabled>按住说话</button>
    </div>
    <div class="panel">
      <div class="row"><div class="label">连接状态</div><div id="status">未连接</div></div>
      <div class="row"><div class="label">识别文本</div><div id="stt">-</div></div>
      <div class="row"><div class="label">舒心回复</div><div id="reply">-</div></div>
      <div class="row"><div class="label">耗时</div><div id="timing">-</div></div>
    </div>
    <div class="panel"><div id="log"></div></div>
  </main>
  <script>
    const statusEl = document.getElementById('status');
    const sttEl = document.getElementById('stt');
    const replyEl = document.getElementById('reply');
    const timingEl = document.getElementById('timing');
    const logEl = document.getElementById('log');
    const connectBtn = document.getElementById('connect');
    const recordBtn = document.getElementById('record');
    const userInput = document.getElementById('userId');
    const tokenInput = document.getElementById('userToken');
    const deviceInput = document.getElementById('deviceId');
    let ws, audioContext, source, processor, stream;
    let recording = false;
    let recordingRequested = false;
    let startingRecording = false;

    function log(line) {{
      logEl.textContent += `${{new Date().toLocaleTimeString()}} ${{line}}\\n`;
      logEl.scrollTop = logEl.scrollHeight;
    }}

    function wsUrl() {{
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      return `${{protocol}}//${{location.host}}/ws/voice`;
    }}

    connectBtn.onclick = () => {{
      if (recording || startingRecording) return;
      if (ws && ws.readyState === WebSocket.OPEN) ws.close();
      ws = new WebSocket(wsUrl());
      ws.binaryType = 'arraybuffer';
      connectBtn.disabled = true;
      statusEl.textContent = '连接中';
      ws.onopen = () => {{
        statusEl.textContent = '已连接';
        recordBtn.disabled = false;
        connectBtn.disabled = false;
        ws.send(JSON.stringify({{
          type: 'hello',
          user_id: userInput.value,
          token: tokenInput.value,
          device_id: deviceInput.value,
          client_id: 'web-demo'
        }}));
      }};
      ws.onclose = () => {{
        statusEl.textContent = '已断开';
        recordBtn.disabled = true;
        connectBtn.disabled = false;
      }};
      ws.onerror = () => {{
        log('WebSocket error');
        connectBtn.disabled = false;
      }};
      ws.onmessage = (event) => {{
        if (typeof event.data !== 'string') {{
          const blob = new Blob([event.data], {{type: 'audio/mpeg'}});
          new Audio(URL.createObjectURL(blob)).play();
          return;
        }}
        const msg = JSON.parse(event.data);
        log(JSON.stringify(msg));
        if (msg.type === 'stt' && msg.state === 'final') sttEl.textContent = msg.text || '-';
        if (msg.type === 'agent' && msg.state === 'reply') replyEl.textContent = msg.text || '-';
        if (msg.type === 'tts' && msg.state === 'stop') {{
          timingEl.textContent = `STT/Agent/TTS 总耗时 ${{msg.total_elapsed_ms}}ms`;
          recordBtn.disabled = false;
          recordBtn.textContent = '按住说话';
        }}
        if (msg.type === 'error') {{
          recordBtn.disabled = false;
          recordBtn.textContent = '按住说话';
        }}
      }};
    }};

    async function startRecording() {{
      if (!ws || ws.readyState !== WebSocket.OPEN) {{
        log('请先点击连接');
        return;
      }}
      if (recording || startingRecording) return;
      recordingRequested = true;
      startingRecording = true;
      recordBtn.classList.add('recording');
      recordBtn.textContent = '录音中';
      connectBtn.disabled = true;
      sttEl.textContent = '-';
      replyEl.textContent = '-';
      timingEl.textContent = '-';
      try {{
        stream = await navigator.mediaDevices.getUserMedia({{audio: true}});
        audioContext = new AudioContext();
        source = audioContext.createMediaStreamSource(stream);
        processor = audioContext.createScriptProcessor(4096, 1, 1);
        processor.onaudioprocess = (event) => {{
          if (!recording || ws.readyState !== WebSocket.OPEN) return;
          const input = event.inputBuffer.getChannelData(0);
          const pcm = downsampleToPcm16(input, audioContext.sampleRate, 16000);
          if (pcm.byteLength) ws.send(pcm);
        }};
        source.connect(processor);
        processor.connect(audioContext.destination);
        startingRecording = false;
        if (!recordingRequested) {{
          await cleanupAudio();
          restoreReadyState();
          return;
        }}
        recording = true;
        ws.send(JSON.stringify({{type: 'listen', state: 'start'}}));
      }} catch (error) {{
        log(`麦克风启动失败: ${{error.message || error}}`);
        startingRecording = false;
        recordingRequested = false;
        recording = false;
        await cleanupAudio();
        restoreReadyState();
      }}
    }}

    async function stopRecording() {{
      if (!recording && !startingRecording && !recordingRequested) return;
      recordingRequested = false;
      if (startingRecording && !recording) {{
        recordBtn.textContent = '处理中';
        return;
      }}
      recording = false;
      recordBtn.classList.remove('recording');
      recordBtn.textContent = '处理中';
      recordBtn.disabled = true;
      if (ws && ws.readyState === WebSocket.OPEN) {{
        ws.send(JSON.stringify({{type: 'listen', state: 'stop'}}));
      }}
      await cleanupAudio();
      connectBtn.disabled = false;
    }}

    async function cleanupAudio() {{
      if (processor) processor.disconnect();
      if (source) source.disconnect();
      if (stream) stream.getTracks().forEach(track => track.stop());
      if (audioContext) await audioContext.close();
      processor = null;
      source = null;
      stream = null;
      audioContext = null;
    }}

    function restoreReadyState() {{
      recordBtn.classList.remove('recording');
      recordBtn.textContent = '按住说话';
      recordBtn.disabled = !ws || ws.readyState !== WebSocket.OPEN;
      connectBtn.disabled = false;
    }}

    recordBtn.addEventListener('pointerdown', (event) => {{
      event.preventDefault();
      recordBtn.setPointerCapture(event.pointerId);
      startRecording();
    }});
    recordBtn.addEventListener('pointerup', (event) => {{
      event.preventDefault();
      stopRecording();
    }});
    recordBtn.addEventListener('pointercancel', (event) => {{
      event.preventDefault();
      stopRecording();
    }});
    recordBtn.addEventListener('pointerleave', (event) => {{
      if (recording || startingRecording || recordingRequested) stopRecording();
    }});

    function downsampleToPcm16(input, fromRate, toRate) {{
      const ratio = fromRate / toRate;
      const length = Math.floor(input.length / ratio);
      const output = new Int16Array(length);
      for (let i = 0; i < length; i++) {{
        const sample = input[Math.floor(i * ratio)];
        const clamped = Math.max(-1, Math.min(1, sample));
        output[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
      }}
      return output.buffer;
    }}
  </script>
</body>
</html>"""


def main() -> None:
    args = build_parser().parse_args()
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError(
            "uvicorn is not installed. Add voice web dependencies and rebuild Docker."
        ) from exc
    app = create_app(args.device_config, args.users_config, args.default_device_id, args.out_dir)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
