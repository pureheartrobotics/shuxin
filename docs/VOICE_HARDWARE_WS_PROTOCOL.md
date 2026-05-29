# 语音硬件 WebSocket 接口协议

本文档面向后续硬件接入方。当前协议用于无硬件 Web 测试台，也作为后续真实硬件的最小接入边界。

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

上行音频帧格式：

```text
sample_rate: 16000 Hz
channels: 1
sample_format: PCM16
byte_order: little-endian
container: none
```

硬件不要发送 wav/mp3/opus 文件。`listen start` 后直接发送 PCM16 二进制帧，`listen stop` 表示一句话结束。

## 3. 设备上行文本消息

连接建立后先发送 `hello`。

真实硬件接入推荐使用设备身份，而不是让设备携带用户身份：

```json
{"type":"hello","device_code":"ESP32_MAC_OR_EFUSE_CODE","device_secret":"shared-secret-for-prototype","client_id":"device-001","session_id":"optional-session-id"}
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

## 4. 设备上行二进制消息

在 `listen start` 和 `listen stop` 之间发送音频二进制帧：

```text
<pcm16 audio frame bytes>
```

建议每帧 20ms 到 100ms。默认本地 STT 会把一轮音频暂存在内存中，收到 `listen stop` 后再进入识别；当设备 STT 配置为 `tencent-realtime` 时，服务端会在 `listen start` 后把 PCM 持续转发到腾讯云实时语音识别。

## 5. 服务端下行文本消息

服务端连接就绪：

```json
{"type":"hello","state":"ready","device_id":"demo-device-001"}
```

设备 hello 确认：

```json
{"type":"hello","state":"ok","user_id":"demo-user","device_id":"demo-device-001","client_id":"device-001","session_id":"optional-session-id"}
```

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
{"type":"stt","state":"sentence_final","text":"你好，舒心","elapsed_ms":1200}
```

最终识别文本：

```json
{"type":"stt","state":"final","text":"你好，舒心","elapsed_ms":1234}
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

```json
{"type":"tts","state":"start"}
```

单句 TTS 开始/结束（流式分句下发）：

```json
{"type":"tts","state":"sentence_start","text":"你好，","index":1,"total_elapsed_ms":2500}
{"type":"tts","state":"sentence_stop","text":"你好，","index":1,"elapsed_ms":900,"total_elapsed_ms":3400}
```

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

当前 demo 在 `tts start` 后按句发送 mp3 二进制（每句一对 `sentence_start` / `sentence_stop`），并在本轮完成后发送 `tts stop`：

```text
<mp3 audio bytes>
```

硬件第一版可以把该 mp3 缓存完整后播放。后续如需低延迟播放，再扩展为分句 TTS 或流式 TTS。

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
换取 `openid`，再返回舒心自己的 `session_token`。`session_key` 只留在服务端，
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

新版小程序优先提交 `session_token`；旧的 `{"wx_code":"...","device_code":"..."}`
仍保留兼容，主要用于开发测试。为兼容旧小程序包，如果 `device_code` 里误传了
外壳公开码，后端会在查不到内部设备时再按 `claim_code` 兜底查一次。

我的设备：

```http
POST /api/devices/my
{"session_token":"..."}
```

解绑：

```http
POST /api/devices/unbind
{"session_token":"...","device_code":"..."}
```

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

新制码设备默认使用 `devices.auth_mode='per_device_secret'` 和 `device_secret_hash`。后台只允许轮换设备密钥并一次性展示新密钥，不提供直接编辑设备密钥明文的入口。

## 9. 当前边界

当前 demo 暂不支持：

- 自动 VAD。
- Opus 音频上行。
- 流式 TTS。
- 中途打断播放。
- MQTT。
- OTA。
- 后台一键生成和轮换每设备独立密钥。

当前目标是先跑通准实时 turn-based 对话：用户说完一句，硬件发送 `listen stop`，服务端返回识别文本、Agent 回复和回复音频。
