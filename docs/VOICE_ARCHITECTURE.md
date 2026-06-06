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
  -> STT final（tencent-realtime 通常 <200ms）
  -> agent/thinking
  -> Agent 流式 delta -> 按标点/逗号分句 TTS
  -> WebSocket 二进制 mp3 分句下发
  -> 浏览器播放
```

典型延迟（本地 Docker + DeepSeek API 可达时）：STT 完成后约 3–6s 出现首段 `agent/delta`，首段 TTS 紧随其后。失败时先发 `agent/error`（`error_kind`）再降级，不应长时间空等。

这个阶段的实时目标是“用户说完一句后几秒内听到回复”，不是边说边打断、自动 VAD 或流式 TTS。

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

- STT：腾讯云实时识别 `tencent-realtime`（生产默认）；本地 FunASR 为开发 fallback。
- TTS：火山语音复刻 `volcengine-clone`（生产默认）；EdgeTTS 仅脚本试听。

准实时测试 provider：

- STT：`tencent-realtime` 或 FunASR streaming-local。
- TTS：火山复刻，按用户绑定的 `agents` 记录解析 `voice_type`。

低延时实时 STT provider：

- STT：腾讯云实时语音识别 WebSocket，配置类型为 `tencent-realtime`。
- 浏览器/硬件仍向舒心服务端发送 16k mono PCM16；服务端在 `listen start` 后连接腾讯云 ASR，并在录音期间持续转发 PCM。
- 腾讯云返回的中间结果会下发为 `stt partial`，稳定句子结果下发为 `stt sentence_final`；`listen stop` 后用累积文本进入 Agent 和 TTS。
- 需要环境变量 `TENCENT_ASR_APPID`、`TENCENTCLOUD_SECRET_ID`、`TENCENTCLOUD_SECRET_KEY`，设备配置示例见 `data/devices.yaml.example`。

同时保留 API provider 的接口位置，后续可以把 `ProviderConfig.type` 切到 `api` 后实现远程服务调用。

## 3.1 后续：STT/TTS API 化路线

当前 STT/TTS 生产组合：

- STT 默认腾讯云实时识别（`tencent-realtime`），适合低延迟 turn-based 对话。
- TTS 默认火山语音复刻（`volcengine-clone`），音色由 Postgres `agents` 表与用户 `agent_id` 绑定管理。

本地 FunASR 与 EdgeTTS 保留为开发 fallback（`type=local` 会打 deprecation 日志）。

阶段计划：

1. 先补齐 API provider 的接口约定和测试，用 mock API 跑通 `语音 -> STT API -> Agent -> TTS API -> 音频`。
2. 再接入第一个低成本/免费额度供应商，保证不下载本地 STT 模型也能完成最小闭环。
3. 后台预留管理员配置入口，可以按设备或设备组设置 STT/TTS 的 `api_url`、`api_key`、`model` 和 `voice`。
4. 生产前再补充预算、限流、失败重试、错误提示和供应商降级策略。

配置归属保持简单：

- LLM 模型 API 继续挂在用户侧，支持按用户套餐和额度调整。
- STT/TTS 先挂在系统/设备侧，由管理员配置；普通用户不能自己配置语音供应商。
- 后续如果套餐需要区分语音质量，再在后台增加设备组或套餐级覆盖，不先做复杂用户自定义。

## 3.2 三层记忆与上下文

语音路径不追求「无限回合原文」进 LLM，而是分层：

| 层级 | 内容 | 默认规模 |
|------|------|----------|
| 短期 | `Agent` 会话 `short_term` 最近原文 | `SHUXIN_VOICE_MAX_HISTORY=8` |
| 中期 | `shared_memory` 的 7 日 `rolling_summary` + 规则 `recent_topics` | 每 `SHUXIN_SUMMARY_EVERY_N` 轮（默认 5）及 WebSocket 断线时异步合并 |
| 长期 | `facts.json` / Postgres `user_facts` + 陪伴插件状态 | 规则抽取 + 既有 companion 持久化 |

实现见 `src/shuxin/voice/memory_summary.py`。`record_turn` 后规则更新 topics；满足轮次或断线时 `maybe_merge_rolling_summary` 调用便宜模型合并摘要，并同步 `~/.shuxin/users/{user_id}/summaries/shared_memory.json` 供陪伴插件注入。重连**不**从 `conversation_events` 恢复最近原文，仅依赖中期摘要与长期 facts。

环境变量：`SHUXIN_SUMMARY_EVERY_N`、`SHUXIN_SUMMARY_MODEL`、`SHUXIN_SUMMARY_MAX_TOKENS`。`compress_if_needed` 仍只处理音频附件配额，与对话摘要无关。

CLI 默认 `max_history=30`（全局配置），与语音短期窗口独立。

voice-demo 人工验收步骤见 [VOICE_DEMO_MIN_TEST.md §11](VOICE_DEMO_MIN_TEST.md)。

## 3.3 TTS 火山语音复刻（Volcengine OpenSpeech）

生产默认使用火山引擎 **语音复刻** 合成 API（`POST https://openspeech.bytedance.com/api/v1/tts`），复刻音色在控制台完成一次即可长期使用。合成链路 **无 karen/FFmpeg 后处理**，直出 mp3。

配置分层（横切 resolver，见 `src/shuxin/voice/tts_config.py`）：

| 层 | 说明 |
|------|------|
| Postgres `agents` | 运行时主数据源：`voice_type`、`cluster`、`soul_path`、人格 metadata |
| `users.agent_id` | 用户绑定的 Agent（管理员配置）；WebSocket TTS 据此选音色 |
| `devices.metadata.mbti` | 盲盒设备 MBTI，注入 Identity（语气差异，音色同 user.agent） |
| env | 共享 `VOLCENGINE_TTS_API_KEY`、`VOLCENGINE_TTS_API_URL`；可选 env 兜底 `VOLCENGINE_TTS_VOICE_TYPE` |
| `data/tts_profiles.yaml` | 无 DATABASE_URL 时的 YAML fallback |
| Admin API | `GET/POST/PATCH/DELETE /admin/api/agents`；`POST /admin/api/tts/preview`；`PATCH /admin/api/users/{id}` |

| 配置 | 说明 |
|------|------|
| `tts.type` | `volcengine-clone`（生产默认；迁移 `004_*` + 「全部应用火山 TTS」） |
| `users.agent_id` | 引用 `agents.agent_id`（默认 `shuxin`） |
| `SHUXIN_TTS_TIMEOUT_SECONDS` | HTTP 合成超时（默认 30） |

试听：`python -m shuxin.voice.cli tts "你好，我是舒心。" --out outputs/volc-demo.mp3`（需配置 `VOLCENGINE_TTS_API_KEY` 与 `VOLCENGINE_TTS_VOICE_TYPE`）。

Edge TTS + karen FX 仅保留于 `scripts/generate_voiceover_candidates.py` 等试听脚本，不再用于生产 WebSocket 路径。

**历史参考**：`outputs/voiceover-candidates/` 与 `scripts/generate_voiceover_candidates.py` 用于 Edge 音色候选对比。

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
- STT/TTS 属于基础语音能力，先由管理员在系统/设备侧配置，不开放给普通用户自定义。

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
- `device_status`：设备在线状态、当前 session、`last_error`（WebSocket 连接时置 `online=true`）。
- `devices.status`：生命周期 `provisioned` / `bound` / `disabled`；管理后台与 `device_status.online`、认领码状态、active binding 组合展示。
- `devices.device_secret_encrypted`：可选 Fernet 密文，供后台与 `/voice-demo` 测试台读取（需 `SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY`）。
- `voice_sessions` / `conversation_events` / `audio_attachments`：语音会话、对话轮次和音频附件索引。

绑定规则：

- 条形码只代表公开 `claim_code`，不包含设备编号和设备密钥。
- `claim_code` 绑定后标记为 claimed；用户或后台解绑成功后恢复为 active，后台也可显式重置以支持售后换绑。
- 每台设备同一时间只能有一个 active binding。
- 用户解绑设备时只解除设备访问权，不删除用户记忆。
- 模型 API key 挂在用户上，设备鉴权后按 active binding 找到用户并使用用户级 LLM 配置。
- 合并规则：[`merge_llm_device_config()`](../../src/shuxin/voice/config.py) 将用户 `llm_config` 覆盖到设备默认 LLM，但**空字符串不会清掉**已有字段。Postgres 中若存在 `{"model":"","base_url":""}` 这类记录，在修复前会导致 WebSocket 误用全局默认模型；可执行 `UPDATE users SET llm_config='{}'::jsonb WHERE user_id='demo-user';` 清理，或只在 admin 填写完整 LLM 配置。

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

固件侧如何经 WebSocket 间接使用 STT/TTS、鉴权前置条件与常见错误，见 [硬件 STT/TTS 调用与鉴权接入指南](VOICE_HARDWARE_INTEGRATION.md)。

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

同一个用户的多台设备共享用户记忆和人格成长；设备只决定语音、模型配置和访问入口。音频附件 retention 分两层：

1. **TTL（主策略）**：`SHUXIN_AUDIO_RETENTION_HOURS` 默认 12；voice server 周期任务（`SHUXIN_AUDIO_RETENTION_INTERVAL_SEC` 默认 1800）删除过期 input/reply 磁盘文件，并软删 `audio_attachments` 索引；`conversation_events` 文字保留。
2. **Quota（兜底）**：`users.audio_quota_mb` 默认 512；12 小时内若异常堆积仍触发 `compress_if_needed`，把最旧未压缩 input wav 压成 32kbps mono mp3。

长期陪伴记忆不依赖热存音频无限增长，而依赖事件、摘要、用户画像和人格成长状态。

## 7. 成功标准

当前阶段成功标准：

- `stt samples/demo.wav` 可用。
- `tts "你好"` 可用。
- `chat-audio samples/demo.wav` 可用。
- `session` 可以生成 `init.mp3`、`reply-001.mp3` 和 `transcript.txt`。
- Docker 常驻容器可通过 `scripts/redeploy_docker.sh` 重启；跨主机迁移见 `export_pack.sh` / `import_deploy.sh`（[`VOICE_DEMO_MIN_TEST.md`](VOICE_DEMO_MIN_TEST.md) §12–13）。

后续硬件阶段成功标准：

- 只新增 WebSocket transport。
- 复用现有 `VoiceSessionRunner` 或其会话编排思想。
- 不替换舒心 Agent 核心。
