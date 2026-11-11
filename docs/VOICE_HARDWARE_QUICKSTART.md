# 硬件快速接入（固件工程师）

> **阅读顺序**：完整端到端流程与状态机见 [VOICE_HARDWARE_HANDBOOK.md](VOICE_HARDWARE_HANDBOOK.md)；本文档为 1 页速查。

面向 ESP32 等设备的 **最小联调清单**。协议细节见 [VOICE_HARDWARE_WS_PROTOCOL.md](VOICE_HARDWARE_WS_PROTOCOL.md)；鉴权与云能力边界见 [VOICE_HARDWARE_INTEGRATION.md](VOICE_HARDWARE_INTEGRATION.md)；**TTS 下行（火山合成 → Opus 发包，固件无需 ffmpeg）** 见 [VOICE_HARDWARE_TTS_DOWNLINK.md](VOICE_HARDWARE_TTS_DOWNLINK.md)。

## 1. 服务地址

| 用途 | 地址 | host 来源 |
|------|------|-----------|
| WebSocket 语音（**固件唯一运行时通道**） | `ws://<host>:8765/ws/voice` | 工厂 IT / 现场运维下发；当前无公网域名时多为局域网 `192.168.x.x` |
| 健康检查 | `http://<host>:8765/health` | 同上 |
| 浏览器测试台 | `http://<host>:8765/voice-demo`（PCM/mp3，非 Opus） | 同上 |

**固件不调用 HTTP `/api/...`**。语音 WebSocket 采用**轻量连接**：只报 `user_name`（用户名）+ `robot_code`（机器人代号，可与 `device_code` 同义）；**不要求** `device_secret`、也不要求先开微信账号。

**当前局域网阶段（双路径）**：

1. **固件**：配置 `host=<LAN_IP>` → 连 `ws://<LAN_IP>:8765/ws/voice`
2. **QA 小程序**：编译前设 `SHUXIN_API_BASE=http://<LAN_IP>:8765`，与固件指向**同一台** Voice 服务

详表与步骤清单见 [VOICE_HARDWARE_HANDBOOK.md §2.10](VOICE_HARDWARE_HANDBOOK.md)。

## 2. 前置条件

### 2.1 轻量对话（当前主路径）

1. 板子/客户端知道：服务端 host、`user_name`、`robot_code`
2. 服务端已配置全局/默认 STT、TTS、LLM（`.env` / Admin）
3. 连上 `/ws/voice` 后发连接消息（见 §3），收到 `hello state=ok` 即可 `listen`

服务端会按用户名自动建/复用用户，按机器人代号建/复用设备并完成绑定；设备若被 Admin 禁用则拒绝。

### 2.2 工厂制码 / 小程序绑定（运营侧，可选）

Admin 批量制码、`claim_code` 贴码、微信绑机等流程仍可用于量产运营；**固件 WS 握手不再依赖烧录 `device_secret`**。工厂验收细则见 [FACTORY_ACCEPTANCE_HANDOFF.md](FACTORY_ACCEPTANCE_HANDOFF.md)。

## 3. 连接与鉴权（Opus 硬件路径）

连接后 **先发** 用户名 + 机器人代号（可带 `type: hello`，也可作为首条 JSON；兼容旧字段名 `device_code` = `robot_code`）：

```json
{
  "type": "hello",
  "user_name": "小林",
  "robot_code": "car-001",
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
  "user_name": "小林",
  "device_id": "car-001",
  "robot_code": "car-001",
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

### 出厂验收 hello 成功（`factory_acceptance`）

```json
{
  "type": "hello",
  "state": "ok",
  "user_id": "factory_probe",
  "device_id": "SX-000116",
  "factory_acceptance": true
}
```

此模式下：**保持连接**；监听 `factory_verify` 并回 `factory_verify_ack`；**禁止** `listen`。见 [FACTORY_ACCEPTANCE_HANDOFF.md](FACTORY_ACCEPTANCE_HANDOFF.md)。

## 4. 一轮语音对话（仅绑定后）

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
- 固件 C 语言 i18n 表须与 JSON **字符串一致**（含 `CHECK_NEW_VERSION_FAILED`、`FOUND_NEW_ASSETS`、`FACTORY_VERIFY_SUCCESS`、`FACTORY_VERIFY_FAILED` 的固定句）

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
| `device is not bound` | 非出厂路径：用户未绑定；或设备已绑定却期望 `factory_acceptance` |
| hello 无 `factory_acceptance` | 设备已有 active binding，或 `status` 不是 `provisioned` |
| QA `device_offline` | hello 后 WS 断开 |
| QA `ack_timeout` | 未在 10s 内回 `factory_verify_ack` |
| `opus support requires opuslib_next` | 服务端 Docker 未 redeploy |
| `no audio received` | `listen stop` 前未发 Opus 帧 |
