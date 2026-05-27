# 舒心语音闭环与硬件接口架构

本文档说明当前语音 demo 的边界：我们参考小智项目的成熟服务端形态，但不复制它的产品核心。舒心自己的核心仍然是 Agent 主循环、人格、记忆、插件和陪伴编排。

硬件接入方优先阅读：[语音硬件 WebSocket 接口协议](VOICE_HARDWARE_WS_PROTOCOL.md)。

## 1. 架构边界

可以参考小智的部分：

- WebSocket 硬件连接模型。
- `hello / listen / abort / ping` 这类设备控制消息。
- 设备上行二进制音频帧。
- 服务端下发 STT/TTS 状态消息。
- TTS 音频帧按节奏下发。
- `device_id / client_id / per-device config` 的设备配置思路。

舒心自己保留的部分：

- `Agent` 主循环。
- `SOUL.md` 和 personality。
- memory/plugin/companion 编排。
- 每轮对话的语义处理。
- 未来多产品、多角色、多设备的配置策略。

暂时不复制的部分：

- 完整连接管理。
- VAD。
- MQTT。
- OTA。
- 生产级并发和流式 Opus 帧调度。

## 2. 当前无硬件闭环

当前实现先保证没有硬件也能跑通完整链路：

```text
机器人初始化
  -> welcome_text
  -> TTS
  -> outputs/session/init.mp3
  -> 输入用户音频文件路径
  -> STT
  -> 用户文字
  -> ShuXin Agent
  -> 回复文字
  -> TTS
  -> outputs/session/reply-001.mp3
  -> transcript.txt
```

运行入口：

```bash
python -m shuxin.voice.cli session \
  --device-id demo-device-001 \
  --out-dir outputs/session
```

会话启动后会先生成：

- `outputs/session/init.mp3`
- `outputs/session/transcript.txt`

每轮输入一个音频文件路径，例如：

```text
samples/demo.wav
exit
```

每轮会生成：

- `outputs/session/reply-001.mp3`
- `outputs/session/reply-002.mp3`
- `outputs/session/transcript.txt`

## 2.1 WebSocket 准实时测试台

在没有硬件时，浏览器可以作为假硬件接入常驻 voice server：

```bash
python -m shuxin.voice.server --host 0.0.0.0 --port 8765
```

浏览器打开：

```text
http://localhost:8765/voice-demo
```

第一版准实时链路：

```text
浏览器按住说话
  -> Web Audio 采集麦克风
  -> 下采样为 16k mono PCM16
  -> WebSocket 二进制音频帧上行
  -> 松手发送 listen stop
  -> 服务端写临时 wav
  -> STT final transcript
  -> ShuXin Agent
  -> EdgeTTS 合成 mp3
  -> WebSocket 二进制 mp3 下发
  -> 浏览器播放
```

这个阶段的实时目标是“用户说完一句后几秒内回复”，不是边说边打断、自动 VAD 或流式 TTS。

## 3. 当前代码分层

语音 demo 的代码在 `src/shuxin/voice/` 下：

- `db.py`：asyncpg 连接池与迁移入口。
- `migrations/`：voice Postgres SQL 迁移。
- `postgres_repository.py`：Postgres 用户、设备、绑定、事件和附件仓储。
- `local_repository.py`：未配置 `DATABASE_URL` 时的 YAML demo fallback。
- `audio_files.py`：用户音频附件路径、额度和压缩策略。
- `config.py`：设备级配置，后续可以替换成远程设备配置服务。
- `providers.py`：STT/TTS provider 抽象与实现。
- `service.py`：语音服务门面，保留原有 `stt / tts / chat-audio` 单点能力。
- `transport.py`：硬件输入输出抽象，目前用文件模拟麦克风和扬声器。
- `session.py`：无硬件语音闭环，会话内复用同一个 Agent。
- `server.py`：WebSocket voice server 和浏览器测试台。
- `cli.py`：命令行入口。

当前默认 provider：

- STT：本地 FunASR `models/SenseVoiceSmall`。
- TTS：EdgeTTS。

准实时测试 provider：

- STT：FunASR `models/paraformer-zh-streaming`，配置类型为 `streaming-local`。
- TTS：第一版仍然使用 EdgeTTS 整段 mp3 返回。

同时保留 API provider 的接口位置，后续可以把 `ProviderConfig.type` 切到 `api` 后实现远程服务调用。

## 4. Transport 预留接口

当前接口：

```text
AudioInputTransport
  read_user_audio_path() -> Path | None

AudioOutputTransport
  publish_audio(audio_path: Path) -> None

DeviceSession
  device_id
  client_id
  turn_index
  metadata
```

当前无硬件替代：

- `TerminalFileInputTransport`：用户在终端输入 `samples/*.wav`，模拟麦克风输入。
- `FileAudioOutputTransport`：把 TTS 结果写到 `outputs/session/*.mp3`，模拟扬声器输出。

未来接硬件时，优先替换 transport：

- 文件输入替换成 WebSocket 上行音频帧。
- 文件输出替换成 WebSocket/Opus 音频帧下发。
- `DeviceSession` 继续保存 `device_id`、`client_id`、会话状态和 Agent 配置。

不要为了接硬件重写舒心 Agent/STT/TTS 主链路。

## 5. 未来硬件协议形态

未来 WebSocket 硬件接口可以参考小智的消息形态。

设备上行文本消息：

```json
{"type":"hello","device_id":"demo-device-001","client_id":"client-001"}
```

```json
{"type":"listen","state":"start"}
```

```json
{"type":"listen","state":"stop"}
```

```json
{"type":"abort"}
```

```json
{"type":"ping"}
```

设备上行二进制消息：

```text
audio frame bytes
```

服务端下行文本消息：

```json
{"type":"stt","text":"你好，舒心"}
```

```json
{"type":"tts","state":"start"}
```

```json
{"type":"tts","state":"sentence_start","text":"你好，我在。"}
```

```json
{"type":"tts","state":"stop"}
```

服务端下行二进制消息：

```text
tts audio frame bytes
```

当前浏览器测试台已使用同一协议方向：

- 文本消息处理 `hello / listen start / listen stop / abort / ping`。
- 二进制上行使用 16kHz mono PCM16。
- 二进制下行第一版使用完整 mp3。

## 6. 多设备配置与绑定方向

当前语音模块支持两种数据来源：

- 配置 `DATABASE_URL` 时，启动时连接 Postgres、执行 `src/shuxin/voice/migrations/*.sql`，并把开发 YAML seed 到数据库。
- 未配置 `DATABASE_URL` 时，继续走 `data/devices.yaml` / `data/users.yaml` 和本地文件存储，作为浏览器 demo fallback。

`data/devices.yaml` 和 Postgres 设备配置都按设备 ID 保存：

- 每个用户可以有自己的 LLM provider/model/base_url/api_key；设备鉴权后按绑定关系使用用户级 LLM 配置。
- 每个设备可以有自己的 STT provider/model_dir/api_url/api_key。
- 每个设备可以有自己的 TTS provider/voice/api_url/api_key。

调用方仍然只按 `device_id` / `device_code` 获取配置。RDS 迁移时只需要把 `DATABASE_URL` 指向新库并执行同一套迁移脚本。

## 6.1 硬件绑定模型

真实硬件不是开放 SaaS 多租户模型，而是硬件绑定型产品：

```text
微信用户 openid -> claim_code(外壳条形码) -> device_id + device_secret -> 设备访问用户资产
```

第一阶段内部原型：

- 管理后台批量生成 `device_id`、一次性可见的 `device_secret` 和外壳公开 `claim_code`。
- 后端把设备和公开码写入数据库，`device_secret` 只保存 hash。
- 工人把 `device_id + device_secret` 烧录进设备，外部条形码只暴露 `claim_code`。
- 用户小程序先调用 `/api/wechat/login` 换取舒心 `session_token`，扫码后再提交 `session_token + claim_code` 建立 active binding。
- 设备 WebSocket `hello` 使用 `device_code + device_secret`；后端鉴权通过后才允许访问绑定用户资产和模型 API。

数据库使用 `devices.auth_mode` 和 `device_secret_hash` 支持逐台设备独立密钥。

核心表：

- `users`：用户配置、模型 API 配置、音频额度、人工 token 额度和软删除状态。
- `devices`：设备配置、鉴权模式、设备状态和软删除状态。
- `device_claim_codes`：外壳公开码明文、hash、认领状态和重置记录。
- `device_bindings`：用户和设备的 active binding；一台设备同一时间只能有一个 active binding。
- `device_binding_events`：绑定、解绑、后台操作等审计事件。
- `device_status`：设备在线状态、当前 session、`last_error`。
- `voice_sessions` / `conversation_events` / `audio_attachments`：语音会话、对话轮次和音频附件索引。

绑定规则：

- 条形码只代表公开 `claim_code`，不包含设备编号和设备密钥。
- `claim_code` 绑定后标记为 claimed；用户或后台解绑成功后恢复为 active，后台也可显式重置以支持售后换绑。
- 每台设备同一时间只能有一个 active binding。
- 用户解绑设备时只解除设备访问权，不删除用户记忆。
- 模型 API key 挂在用户上，设备鉴权后按 active binding 找到用户并使用用户级 LLM 配置。

主要 HTTP 路由：

| 路由 | 用途 |
|------|------|
| `POST /api/factory/devices/provision` | 单台登记设备，生成一次性 `device_secret` 和 `claim_code` |
| `POST /admin/api/factory/devices/batch` | 后台批量生成 `device_id + device_secret + claim_code` 并入库 |
| `GET /admin/api/claim-codes/{claim_code}/barcode.png` | 返回外壳公开码的 Code128 PNG |
| `POST /api/barcodes/decode` | 小程序上传条形码图片后端识别，返回公开码文本 |
| `POST /api/wechat/login` | 小程序提交 `wx_code`，服务端换 openid 并返回自定义 `session_token` |
| `POST /api/devices/bind` | 小程序提交 `session_token + claim_code` 绑定设备；兼容旧 `wx_code/device_code` |
| `POST /api/devices/my` | 小程序按 `session_token` 查询当前用户设备 |
| `POST /api/devices/unbind` | 小程序按 `session_token + device_code` 解绑设备；兼容旧 demo 形式 |
| `GET /admin` | 轻量后台管理页面 |
| `GET/POST/PATCH/DELETE /admin/api/devices` | 后台设备配置 CRUD、外壳码/备注更新，删除为软删除 |
| `POST /admin/api/devices/{device_id}/rotate-secret` | 后台轮换设备密钥，明文新密钥只返回一次 |
| `POST /admin/api/devices/{device_id}/reset-claim` | 后台把最近的外壳码重置为可认领 |
| `GET/POST/DELETE /admin/api/users` | 后台用户配置 CRUD，包含模型 API 配置和人工 token 额度，删除为软删除 |
| `GET/POST /admin/api/bindings` | 后台查看和手动创建用户设备绑定 |
| `POST /admin/api/bindings/unbind` | 后台解绑 active binding |

## 6.2 Web 多用户记忆与附件存储

Web 测试台现在区分三类数据：

- 用户长期资产：`$SHUXIN_HOME/users/{user_id}/`，包含长期记忆、陪伴状态、人格成长状态、事件库和共同记忆摘要。
- 音频附件：`outputs/web/users/{user_id}/{device_id}/{session_id}/`，包含输入录音和回复音频，通过事件库索引回对话轮次。
- 用户/设备配置：Postgres 为权威来源；没有 `DATABASE_URL` 时回退到 `data/users.yaml` 和 `data/devices.yaml`。

真实设备 WebSocket `hello` 携带：

```json
{"type":"hello","device_code":"ESP32_MAC_OR_EFUSE_CODE","device_secret":"shared-secret-for-prototype","client_id":"device-001"}
```

浏览器测试台默认模拟真实硬件，使用 `device_code + device_secret + client_id`。服务端仍兼容旧的 `user_id + token + device_id` 形式，但不作为推荐测试路径。

同一个用户的多台设备共享用户记忆和人格成长；设备只决定语音、模型配置和访问入口。音频附件按用户额度管理，超过额度后优先把旧输入 wav 压缩为 32kbps mono mp3，并保留事件索引。长期陪伴记忆不依赖热存音频无限增长，而依赖事件、摘要、用户画像和人格成长状态。

## 7. 成功标准

当前阶段成功标准：

- `stt samples/demo.wav` 可用。
- `tts "你好"` 可用。
- `chat-audio samples/demo.wav` 可用。
- `session` 可以生成 `init.mp3`、`reply-001.mp3` 和 `transcript.txt`。
- Docker 常驻容器可以通过 `scripts/redeploy_docker.sh` 重启。

后续硬件阶段成功标准：

- 只新增 WebSocket transport。
- 复用现有 `VoiceSessionRunner` 或其会话编排思想。
- 不替换舒心 Agent 核心。
