# 硬件快速接入（固件工程师）

> **阅读顺序**：完整端到端流程与状态机见 [VOICE_HARDWARE_HANDBOOK.md](VOICE_HARDWARE_HANDBOOK.md)；本文档为 1 页速查。

面向 ESP32 等设备的 **最小联调清单**。协议细节见 [VOICE_HARDWARE_WS_PROTOCOL.md](VOICE_HARDWARE_WS_PROTOCOL.md)；鉴权与云能力边界见 [VOICE_HARDWARE_INTEGRATION.md](VOICE_HARDWARE_INTEGRATION.md)。

## 1. 服务地址

| 用途 | 地址 |
|------|------|
| WebSocket 语音 | `ws://<host>:8765/ws/voice` |
| 健康检查 | `http://<host>:8765/health` |
| 浏览器测试台 | `http://<host>:8765/voice-demo`（PCM/mp3，非 Opus） |

## 2. 前置条件

1. 工厂制码：`device_id` + `device_secret` + `claim_code`
2. 固件烧录 **`device_code`（= device_id）+ `device_secret`**
3. 用户小程序绑定设备（`claim_code`）
4. 服务端已配置 STT/TTS/LLM（绑定用户的 `llm_config`、Agent 音色）

未完成绑定时 `hello` 会返回 `device is not bound or disabled`。

## 3. 连接与鉴权（Opus 硬件路径）

连接后 **必须先** 发送 `hello`（含 Opus 协商）：

```json
{
  "type": "hello",
  "device_code": "<device_id>",
  "device_secret": "<secret>",
  "client_id": "device-001",
  "audio_params": {
    "format": "opus",
    "sample_rate": 16000,
    "channels": 1,
    "frame_duration": 60
  }
}
```

成功响应示例：

```json
{
  "type": "hello",
  "state": "ok",
  "user_id": "...",
  "device_id": "...",
  "audio_params": {
    "format": "opus",
    "uplink_sample_rate": 16000,
    "downlink_sample_rate": 24000,
    "channels": 1,
    "frame_duration": 60
  }
}
```

**在收到 `hello ok` 之前不要发送 `listen` 或音频二进制帧。**

## 4. 一轮语音对话

```text
1. {"type":"listen","state":"start"}
2. 每 60ms 发送一帧 raw Opus（16 kHz mono，无 Ogg 头）
3. {"type":"listen","state":"stop"}
4. 收 stt/final → agent/thinking → agent/delta|reply
5. 收 tts/sentence_start → 多帧 Opus 二进制（24 kHz）→ tts/sentence_stop
6. 收 tts/stop
```

固件 **不要** 直连腾讯云 ASR、火山 TTS 或 LLM；密钥只在服务端。

## 5. 系统提示音（本地 Flash）

UI 固定文案（「待命」「电量不足」等）**不经过 WebSocket**，播放预生成 Opus 文件：

- 源文案：[`data/device_assets/strings.zh-CN.json`](../data/device_assets/strings.zh-CN.json)
- 生成产物：[`data/device_assets/zh-CN/`](../data/device_assets/zh-CN/)（`.ogg` + `.opus.bin` + `manifest.json`）
- 固件 C 语言 i18n 表须与 JSON **字符串一致**（含 `CHECK_NEW_VERSION_FAILED`、`FOUND_NEW_ASSETS` 的固定句）

**Flash 编码档**（对齐 xiaozhi-esp32）：**16 kHz / mono / 16 kbps / 60 ms**。与 WebSocket 实时 TTS 下行（24 kHz）分开；固件本地提示音解码器按 `manifest.json` 的 `sample_rate` 配置。

`*.opus.bin` 格式：重复 `[uint16 大端长度][raw Opus packet]`。生成脚本默认 `--format both`，结束后自动删除 `_tmp/`。编码需容器内 `ffmpeg` 带 `libopus`（`shuxin-voice-demo-pg` 镜像已含）；宿主机无 `libopus` 时用 `--reencode-existing` 在 Docker 内离线压档。

生成命令（Docker 内，需 `.env` 火山 TTS 凭证）：

```bash
docker exec shuxin-voice-demo-pg env PYTHONPATH=/app/src \
  python /app/scripts/generate_device_prompt_assets.py \
  --out /app/data/device_assets/zh-CN \
  --format both
```

## 6. 无硬件联调

```bash
docker exec shuxin-voice-demo-pg python scripts/ws_opus_smoke_test.py \
  --url ws://127.0.0.1:8765/ws/voice \
  --device-code demo-device-001 \
  --device-secret dev-device-secret \
  --input /app/data/test/activation.ogg \
  --output /app/outputs/opus-smoke-reply.wav
```

详见 [VOICE_DEMO_MIN_TEST.md §17](VOICE_DEMO_MIN_TEST.md)。

## 7. 常见错误

| 现象 | 排查 |
|------|------|
| `invalid device secret` | 密钥错误或后台轮换后未更新固件 |
| `device is not bound` | 用户未绑定 |
| `opus support requires opuslib_next` | 服务端 Docker 未 redeploy |
| `no audio received` | `listen stop` 前未发 Opus 帧 |
