# 语音硬件 WebSocket 接口协议

> **阅读顺序**：流程与状态机见 [VOICE_HARDWARE_HANDBOOK.md](VOICE_HARDWARE_HANDBOOK.md)；本文档为消息字段与 Admin API 详表。

本文档面向后续硬件接入方。当前协议用于无硬件 Web 测试台，也作为后续真实硬件的最小接入边界。

**STT/TTS 由初心服务端代理调用**，固件不直连云厂商 API。设备须先以 `device_code + device_secret` 完成 WebSocket `hello` 鉴权。已绑定设备可进入语音识别与合成；**未绑定但 `provisioned` 的设备**可走工厂验收会话（`hello_ok.factory_acceptance=true`），仅支持 `factory_verify` / `ping` / `abort`，不可对话。总览见 [硬件 STT/TTS 调用与鉴权接入指南](VOICE_HARDWARE_INTEGRATION.md)。

固件如何获取 `<host>`、局域网双路径联调、出厂验收认知边界见 [VOICE_HARDWARE_HANDBOOK.md §2.10–§2.11](VOICE_HARDWARE_HANDBOOK.md)。

## 1. 服务地址

默认地址：

```text
ws://<host>:8765/ws/voice
```

本机测试：

```text
ws://localhost:8765/ws/voice
```

浏览器测试页：

```text
http://localhost:8765/voice-demo
```

## 2. 音频格式

硬件推荐在 `hello` 中声明 `audio_params.format=opus`；浏览器测试台不传 `audio_params`，默认走 PCM/mp3 兼容路径。

### 2.1 Opus（硬件推荐）

在 `hello` 携带：

```json
"audio_params": {
  "format": "opus",
  "sample_rate": 16000,
  "channels": 1,
  "frame_duration": 60
}
```

服务端 `hello ok` 回应协商结果：

```json
"audio_params": {
  "format": "opus",
  "uplink_sample_rate": 16000,
  "downlink_sample_rate": 24000,
  "channels": 1,
  "frame_duration": 60
}
```

| 方向 | 格式 | 采样率 | 帧长 |
|------|------|--------|------|
| 上行 | raw Opus packet（无 Ogg 头） | 16 kHz mono | 60 ms |
| 下行 | raw Opus packet | 24 kHz mono | 60 ms |

不要发送整段 Ogg/wav/mp3 文件；每个 WebSocket binary 消息 = **一帧 Opus**。服务端内部仍落盘 wav/mp3，与 wire format 无关。

服务端需已安装 `opuslib_next`（[`requirements-voice-app.txt`](../requirements-voice-app.txt)，见 [VOICE_DEMO_MIN_TEST.md §17](VOICE_DEMO_MIN_TEST.md)）；未安装时 `hello` 返回 redeploy 提示。

### 2.2 PCM16（浏览器 / 兼容）

```text
sample_rate: 16000 Hz
channels: 1
sample_format: PCM16
byte_order: little-endian
container: none
```

`listen start` 后直接发送 PCM16 二进制帧，`listen stop` 表示一句话结束。

## 3. 设备上行文本消息

连接建立后先发送 `hello`。

真实硬件接入推荐使用设备身份，而不是让设备携带用户身份：

```json
{"type":"hello","device_code":"ESP32_MAC_OR_EFUSE_CODE","device_secret":"shared-secret-for-prototype","client_id":"device-001","session_id":"optional-session-id","audio_params":{"format":"opus","sample_rate":16000,"channels":1,"frame_duration":60}}
```

当前内部原型阶段，`device_secret` 可以先使用服务端环境变量
`SHUXIN_DEVICE_SHARED_SECRET` 对应的统一密钥。后续量产阶段，服务端会按
`device_code` 校验每台设备独立的密钥哈希。

浏览器测试台默认模拟真实硬件，也发送 `device_code + device_secret`。
服务端会根据设备的 active binding 解析出用户。

旧的用户 token 形式仅作为兼容入口保留，不再作为推荐测试路径：

```json
{"type":"hello","user_id":"demo-user","token":"","device_id":"demo-device-001","client_id":"device-001","session_id":"optional-session-id"}
```

开始录音：

```json
{"type":"listen","state":"start"}
```

结束录音：

```json
{"type":"listen","state":"stop"}
```

取消当前轮：

```json
{"type":"abort"}
```

心跳：

```json
{"type":"ping"}
```

工厂验收回传（收到服务端 `factory_verify` 后立即发送）：

```json
{"type":"factory_verify_ack","verify_id":"<原样回传服务端下发的 verify_id>","status":"ok"}
```

**固件实现要求：**

1. 监听 `type == "factory_verify"` 消息，任何状态下均可处理（Idle / Listening）。
2. 触发本地提示（任选其一）：播放"验收通过"语音 / 屏幕显示 `PASS` 3 秒 / LED 变绿。
3. 立即回传 `factory_verify_ack`，`verify_id` 原样复制，无需理解其含义。
4. 处理完毕后恢复到原状态，不影响进行中或后续的对话流程。
5. 超时窗口为 10 秒，固件只要在此窗口内回传即为有效。

## 4. 设备上行二进制消息

在 `listen start` 和 `listen stop` 之间发送音频二进制帧：

- **Opus 模式**（`hello` 已协商）：每消息一帧 raw Opus packet（16 kHz / 60 ms）
- **PCM 模式**（默认）：裸 PCM16 小端字节

```text
<opus packet bytes>   # format=opus
<pcm16 frame bytes>   # format=pcm 或未声明 audio_params
```

建议 PCM 每帧 20ms 到 100ms。Opus 建议 60ms 一帧。服务端收到 `listen stop` 后进入识别；`tencent-realtime` 模式下服务端在 `listen start` 后持续转发 **解码后的 PCM** 到腾讯云。

## 5. 服务端下行文本消息

服务端连接就绪：

```json
{"type":"hello","state":"ready","device_id":"demo-device-001"}
```

设备 hello 确认（PCM 默认）：

```json
{"type":"hello","state":"ok","user_id":"demo-user","device_id":"demo-device-001","client_id":"device-001","session_id":"optional-session-id"}
```

设备 hello 确认（Opus 协商）：

```json
{"type":"hello","state":"ok","user_id":"demo-user","device_id":"demo-device-001","client_id":"device-001","session_id":"optional-session-id","audio_params":{"format":"opus","uplink_sample_rate":16000,"downlink_sample_rate":24000,"channels":1,"frame_duration":60}}
```

出厂工厂验收 hello 确认（`provisioned` 且未绑定；`user_id` 为内部占位符 `factory_probe`）：

```json
{"type":"hello","state":"ok","user_id":"factory_probe","device_id":"SX-000116","client_id":"device-001","session_id":"…","factory_acceptance":true}
```

- `factory_acceptance: true` 表示当前为出厂验收会话：云端**不会**揭晓/锁定 MBTI（保持 `mbti_status=sealed`），且 `listen` / `text_turn` 会被拒绝。
- 此模式下设备须保持连接，等待 QA 扫码触发 `factory_verify`；收到后本地提示并回 `factory_verify_ack`。

工厂验收指令（QA 扫外壳二维码后由云端触发，设备须立即回传 `factory_verify_ack`）：

```json
{"type":"factory_verify","verify_id":"550e8400-e29b-41d4-a716-446655440000","timestamp":"2026-06-15T05:37:00Z"}
```

- `verify_id`：UUID，必须原样回传。
- 超时窗口 10 秒；超时后云端报告 FAIL，设备无需处理。
- 此消息不影响正常对话流程，设备可任意状态处理。

MBTI 盲盒揭晓（仅 `mbti_status=sealed` 且由 hello 抢先揭晓时；小程序已绑定时通常不再下发）：

```json
{"type":"mbti/reveal","mbti":"INFJ","tagline":"提倡者 — …","is_first_reveal":true}
```

随后可能紧跟固定台词（非 LLM 轮次）：

```json
{"type":"agent","state":"reply","text":"… reveal_script …","elapsed_ms":0}
```

以及 `tts/start` → 音频帧 → `tts/stop`。若小程序绑定已揭晓（`locked`）且 `device_intro_played=false`，hello 补播 TTS 自我介绍（台词为 `绑定成功。` + 各型 `reveal_script`），不再发 `mbti/reveal`。若绑定 API 执行时该设备已有活跃 WebSocket 会话，服务端也会立即推送同一段 TTS；否则等下次 `hello` 补播。`device_intro_played=true` 后不再重复播报。

开始识别：

```json
{"type":"stt","state":"start"}
```

实时识别开始：

```json
{"type":"stt","state":"stream_start"}
```

实时识别中间结果：

```json
{"type":"stt","state":"partial","text":"你好","elapsed_ms":500}
```

实时识别稳定句子结果：

```json
{"type":"stt","state":"sentence_final","text":"你好，初心","elapsed_ms":1200}
```

最终识别文本：

```json
{"type":"stt","state":"final","text":"你好，初心","elapsed_ms":1234}
```

Agent 开始思考（STT 完成后、LLM 首 token 前）：

```json
{"type":"agent","state":"thinking"}
```

Agent 流式片段（可多帧）：

```json
{"type":"agent","state":"delta","text":"你好","elapsed_ms":1200}
```

Agent 调用失败（随后仍可能有降级 `delta`/`reply`）：

```json
{"type":"agent","state":"error","error_kind":"connect_timeout","elapsed_ms":5000}
```

`error_kind` 常见值：`connect_timeout`、`read_timeout`、`auth_error`、`connect_error`、`llm_error`。

Agent 完整回复：

```json
{"type":"agent","state":"reply","text":"你好，我在。","elapsed_ms":1500}
```

开始语音合成：

> 固件向通俗说明（谁合成、Opus 从哪来、**不需要 ffmpeg**）：见 [VOICE_HARDWARE_TTS_DOWNLINK.md](VOICE_HARDWARE_TTS_DOWNLINK.md)。

```json
{"type":"tts","state":"start"}
```

单句 TTS 开始/结束（流式分句下发）：

```json
{"type":"tts","state":"sentence_start","text":"你好，","index":1,"total_elapsed_ms":2500}
{"type":"tts","state":"sentence_stop","text":"你好，","index":1,"elapsed_ms":900,"total_elapsed_ms":3400}
```

> **动作文本与纯动作分句说明**：
> 1. 为了让硬件能捕获动作神态指令以触发对应的实体动作，`tts/sentence_start` 和 `tts/sentence_stop` 广播事件中的 `text` 字段会**保持包含动作括号的原始文本**（如 `"（耳朵微微竖起）你还好吗？"`）。硬件客户端应当解析此字段中的括号来驱动舵机或屏幕显示。
> 2. 合成 TTS 时，括号内的文本会被剥离过滤掉，不会读出声音。
> 3. 当某个分句仅由动作括弧组成、无任何台词时（例如 `"（眼睛笑成月牙，轻轻蹭了蹭你）"`），服务端**依旧会发送 `sentence_start` 和 `sentence_stop` 状态事件**，但**完全跳过 TTS 语音合成且不下发任何音频二进制包**（下发二进制帧数量为 0）。硬件应当在此情况下直接触发物理动作，而不应因为收不到音频而判断为超时或异常。

结束语音合成：

```json
{"type":"tts","state":"stop","elapsed_ms":800,"total_elapsed_ms":3600,"first_agent_delta_ms":1200,"first_tts_audio_ms":2500,"llm_ttft_ms":1200,"error_kind":""}
```

错误：

```json
{"type":"error","message":"no audio received"}
```

心跳响应：

```json
{"type":"pong","ts":1710000000.0}
```

## 6. 服务端下行二进制消息

每句 TTS 在 `tts/sentence_start` 与 `tts/sentence_stop` 之间发送音频：

- **Opus 模式（硬件必须）**：多帧 raw Opus packet（24 kHz / 60 ms），**每帧一条** WebSocket binary 消息；服务端流式转码，边编码边下发，不会把整句 mp3 塞进一条 binary。
- **PCM 兼容模式**：整段 mp3 字节（单条 binary），仅浏览器 Web 测试台使用。

```text
<opus packet bytes> ...   # format=opus，sentence_start/stop 之间，逐包流式
<mp3 audio bytes>         # format=pcm，Web 测试台整段 mp3
```

硬件固件应逐帧解码播放。每条下行 binary 对应 **一个** Opus packet，典型 1–2 KB，**不得超过 4 KB**。带 `device_secret` 的 hello 即使未声明 `audio_params`，服务端也会 **强制 Opus 下行**。

可选环境变量（Docker `.env`）：

| 变量 | 默认 | 说明 |
|------|------|------|
| `SHUXIN_WS_DOWNLINK_MAX_BYTES` | `2048` | 单包告警阈值（上限 4096）；Opus 包不可分割 |
| `SHUXIN_WS_DOWNLINK_YIELD_MS` | `0` | 硬件会话每发一包后的 `asyncio.sleep` 毫秒数，缓解 ESP32 接收队列积压 |

## 7. 微信小程序绑定

小程序端位于 `apps/wechat-miniprogram`，使用 uni-app/Vue。

本地开发：

```bash
export WECHAT_MINIPROGRAM_APPID="your-appid-or-touristappid"
scripts/wechat_miniprogram_dev.sh
```

脚本默认自动探测 WSL IP，并把小程序 API 编译为 `http://<WSL_IP>:8765`。如果要手动指定后端地址，再设置 `SHUXIN_API_BASE`。开发脚本会持续监听源码变化并更新 `dist/dev/mp-weixin`；微信开发者工具只应该打开编译后的 `dist/*/mp-weixin` 目录，不应该打开 `apps/wechat-miniprogram/src`。

Windows 微信开发者工具打开：

```text
apps/wechat-miniprogram/dist/dev/mp-weixin
```

如果需要生产构建：

```bash
scripts/wechat_miniprogram_build.sh
```

微信开发者工具打开：

```text
apps/wechat-miniprogram/dist/build/mp-weixin
```

`dist/build/mp-weixin` 是一次性构建快照。源码变化后需要重新执行 `scripts/wechat_miniprogram_build.sh`，再在微信开发者工具里重新编译或刷新项目，才能拿到最新代码。日常联调用 `scripts/wechat_miniprogram_dev.sh` 更合适。

小程序登录遵循微信官方登录链路：小程序通过 `wx.login()` 获取一次性
`wx_code`，先调用后端 `POST /api/wechat/login`；服务端使用
`SHUXIN_WECHAT_APPID` 和 `SHUXIN_WECHAT_SECRET` 调微信 `code2Session`
换取 `openid`，再返回初心自己的 `session_token`。`session_key` 只留在服务端，
不会下发给小程序。本地没有真实微信配置时，可设置 `SHUXIN_WECHAT_MOCK=1`
使用 mock openid。

设备生产链路使用三码模型：

- `claim_code`：贴在设备外壳上的公开条形码，用户扫码绑定用。
- `device_id` / `device_code`：设备内部编号，设备连接后端时使用。
- `device_secret`：设备内部密钥，只在生成或轮换时一次性展示，数据库只保存 hash。

工厂登记接口返回的 `qr_payload` 是扫码内容，不是图片。贴到设备外部的一维条形码或二维码只应该暴露 `claim_code`，不要包含 `device_id` 或 `device_secret`。小程序扫码逻辑优先接受这些内容：

- 小程序路径或 URL：`/pages/index/index?claim_code=...`
- 原始条形码字符串：`claim_code`
- 旧路径兼容：`device_code=...` 或原始 `device_code`

小程序里“相机扫码”只调用微信原生相机扫码；如果要上传条形码图片，使用“传图识别”，它会把图片发到后端 `POST /api/barcodes/decode` 解析。微信开发者工具的 `scanCode` 上传图片链路对一维条形码不稳定，不能作为后端绑定能力是否正常的判断依据。

图片识别兜底接口：

```http
POST /api/barcodes/decode
{"image_base64":"..."}
```

成功返回：

```json
{"text":"1234567890ABC","format":"CODE_128"}
```

绑定接口：

```http
POST /api/wechat/login
{"wx_code":"..."}

POST /api/devices/bind
{"session_token":"...","claim_code":"..."}

POST /api/devices/bind
{"wx_code":"...","claim_code":"..."}
```

绑定成功且设备仍为 `sealed` 时，响应可含 MBTI 卡片（小程序弹窗用，不含 `reveal_script`）：

```json
{
  "binding_id": "...",
  "device_code": "SX-000001",
  "already_bound": false,
  "mbti": {
    "is_first_reveal": true,
    "mbti": "INFJ",
    "display_name": "提倡者",
    "tagline": "安静而神秘，记得你说过的小事"
  }
}
```

新版小程序优先提交 `session_token`；旧的 `{"wx_code":"...","device_code":"..."}`
仍保留兼容，主要用于开发测试。为兼容旧小程序包，如果 `device_code` 里误传了
外壳公开码，后端会在查不到内部设备时再按 `claim_code` 兜底查一次。

小程序 UI **不提供用户解绑**；`POST /api/devices/unbind` 保留给 Admin/售后。

我的设备：

```http
POST /api/devices/my
{"session_token":"..."}
```

`mbti_status=sealed` 时响应 `device.metadata` 不含 `mbti`；`locked` 后含 `mbti`、`display_name`、`tagline`。

## 8. 后台管理

后台只给管理端使用，不面向普通用户：

```text
http://localhost:8765/admin
```

请求头使用：

```http
X-Admin-Token: <SHUXIN_ADMIN_TOKEN>
```

本地 Docker 默认 token 是 `dev-admin-token`。后台能力包括用户配置、模型 API 配置、批量设备制码、设备状态、用户设备绑定和适配器动作；用户和设备删除采用软删除。

模型 API 配置现在挂在用户上：`/admin/api/users` 的 `llm_config` 保存 provider、model、base_url、api_key。设备通过 `device_code + device_secret` 建立 WebSocket 连接后，服务端先鉴权设备和 active binding，再用绑定用户的 `llm_config` 覆盖设备默认 LLM 配置。STT/TTS 仍保留在设备配置侧。

批量制码接口会一次性写入数据库，并返回明文 `device_secret` 给烧录/导出使用：

```bash
curl -s -H 'X-Admin-Token: dev-admin-token' \
  -H 'Content-Type: application/json' \
  -d '{"device_prefix":"SX","device_start":1,"label_prefix":"CLM","label_batch":"A001","quantity":3}' \
  http://localhost:8765/admin/api/factory/devices/batch
```

返回的每行包含 `device_id`、`claim_code`、一次性 `device_secret`、`qr_payload` 和条形码 PNG URL。后台页面也提供同样的批量制码、CSV 导出和 Code128 PNG 预览。

示例：

```bash
curl -s -H 'X-Admin-Token: dev-admin-token' \
  -H 'Content-Type: application/json' \
  -d '{
    "user_id": "demo-user",
    "enabled": true,
    "token_quota_total": 1000000,
    "llm_config": {
      "provider": "openai-compatible",
      "model": "your-model",
      "base_url": "https://your-api-base/v1",
      "api_key": "your-user-api-key"
    }
  }' \
  http://localhost:8765/admin/api/users
```

新制码设备默认使用 `devices.auth_mode='per_device_secret'`、`device_secret_hash` 和加密列 `device_secret_encrypted`（密钥来自环境变量 `SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY`）。后台可在设备列表「查看」已入库密钥；历史仅 hash 的设备需「换密钥」后才会写入加密列。轮换密钥仍会在响应中一次性返回明文。

## 9. 当前边界

当前 demo 暂不支持：

- 自动 VAD。
- 流式 TTS（下行仍按句分帧，非 token 级流）。
- 中途打断播放。
- MQTT。
- OTA。
- 后台一键生成和轮换每设备独立密钥。

已支持：**Opus 上行 16 kHz / 下行 24 kHz**（`hello` 声明 `audio_params.format=opus`）；浏览器测试台仍用 PCM/mp3。

当前目标是先跑通准实时 turn-based 对话：用户说完一句，硬件发送 `listen stop`，服务端返回识别文本、Agent 回复和回复音频。
