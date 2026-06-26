# 初心 (ChuXin) — 陪伴型 AI 智能体框架

## 项目概述

初心是一个**独立的 AI 智能体框架**，对标 Hermes Agent 的品质标准，专注于陪伴型 AI 场景。

## 核心架构

```
shuxin/
├── core/          # 框架核心（Agent循环、配置、LLM、记忆、插件、人格、身份）
├── cli/           # 命令行交互界面
├── tools/         # 工具注册系统
├── skills/        # 技能管理系统
├── plugins/       # 插件系统
│   └── companion/ # 陪伴插件（自尊、情感、守护、用户建模、拦截器）
├── SOUL.md        # 灵魂文件（人格定义）
└── pyproject.toml # 项目配置
```

## 关键设计决策

1. **独立框架** — 不依赖任何现有框架，从零构建对标 Hermes 品质
2. **插件架构** — 核心功能通过插件系统扩展，陪伴功能作为内置插件
3. **SOUL.md 驱动** — 人格定义从 SOUL.md 加载，可自由定制
4. **MBTI 深度集成** — 人格类型影响行为因子和情感表达
5. **自尊为核心** — 自尊系统是初心的"灵魂"，所有子系统围绕它运转

## 技术栈

- Python 3.11+
- OpenAI API（兼容任意 OpenAI 格式的 API）
- 插件系统（动态导入 + Hook 机制）
- JSON 持久化（~/.shuxin/companion/）

## 快速启动

```bash
pip install -e .
export OPENAI_API_KEY="your-key"
shuxin
```

## 项目架构理解（初始化记录）

### 整体调用链

初心当前是一个 Python `src` layout 项目，主入口在 CLI，核心协调者是 `core/agent.py`。

整体运行链路：

```text
CLI -> Agent.initialize() -> SOUL/Identity/LLM/Memory/Plugin 初始化
    -> Agent.chat() -> 插件 Hook -> LLM 调用 -> 输出转换/拦截 -> 记忆记录
```

`Agent` 负责拼装系统提示、维护会话上下文、调度插件 Hook、调用 LLM，并把用户消息和 AI 回复写入短期记忆。

### 核心模块职责

- `cli/main.py`：命令行交互、首次模型/API key 配置、内置命令分发。
- `core/agent.py`：总协调者，负责初始化子系统、构建系统提示、处理同步/异步/流式对话和斜杠命令。
- `core/config.py`：配置管理，支持 YAML 配置、环境变量覆盖和多模型提供者目录。
- `core/llm.py`：LLM Provider 抽象，当前包含 OpenAI 兼容接口和 Anthropic 接口，支持同步、异步和流式调用。
- `core/soul.py`：加载并解析 `SOUL.md`，生成人格身份提示块。
- `core/identity.py`：管理 MBTI 类型和陪伴行为影响因子。
- `core/memory.py`：管理短期会话记忆和长期 facts JSON 持久化。
- `core/plugin.py`：插件发现、动态加载、Hook 调用、命令注册和工具注册门面。

### 陪伴插件结构

内置陪伴插件位于 `plugins/companion/`，通过 `plugin.yaml` 和 `register(ctx)` 接入插件系统。

它注册的主要 Hook：

- `pre_llm_call`：向系统提示注入自尊、情感状态和用户画像。
- `on_user_message`：处理用户输入，更新自尊、情绪、关系，并评估守护场景。
- `transform_output`：在沉默模式下替换 LLM 输出。
- `on_session_start` / `on_session_end` / `on_ai_message`：处理会话生命周期或预留扩展点。

陪伴插件内部子系统：

- `self_esteem.py`：自尊系统，维护 0-100 自尊值、沉默阈值、自然恢复、提前恢复和持久化状态。
- `emotion.py`：情感引擎，基于关键词、自尊变化和沉默状态更新多维情绪。
- `guardian.py`：守护系统，识别情绪低落、长时间工作、自我否定、愤怒、深夜未眠、需要独处等场景。
- `user_model.py`：用户画像和关系建模，维护亲密度、交互次数、用户名称、喜好等信息。
- `interceptor.py`：响应拦截器，在沉默模式下用预设话术替换模型输出。

### 当前边界

- 协作边界：`src/shuxin/cli/`、`core/`、`plugins/`、`skills/`、`tools/` 归其他协作者维护；设备绑定、数据库接入、后台管理、小程序/硬件协议优先落在 `src/shuxin/voice/`、`apps/wechat-miniprogram/`、`docs/` 和 `scripts/`，通过现有公开接口调用核心能力。
- `tools` 已有注册表和 OpenAI tool schema 转换能力，但尚未接入 `Agent` 的 LLM 调用链。
- `skills` 已有 `SKILL.md` 发现和解析框架，但尚未注入 `Agent` 系统提示或命令流程。
- `tests/` 目录已存在，当前重点覆盖语音 Web 用户和存储相关逻辑；`pyproject.toml` 已配置 pytest。
- 语音模块已落在 `src/shuxin/voice/`，包含 STT/TTS CLI、无硬件会话、WebSocket 浏览器测试台、用户配置、附件存储、后台管理、Postgres 设备绑定和 YAML fallback；生产级 VAD、流式 TTS、每设备独立密钥仍是后续边界。
- 本地 Docker voice 服务使用 `DATABASE_URL` 连接 Postgres；后台 token 为 `SHUXIN_ADMIN_TOKEN`；硬件原型密钥为 `SHUXIN_DEVICE_SHARED_SECRET`；真实小程序登录需要 `SHUXIN_WECHAT_APPID` 和 `SHUXIN_WECHAT_SECRET`，本地可用 `SHUXIN_WECHAT_MOCK=1`。

### 语音 LLM 与 WebSocket 约束

- Postgres 用户 `llm_config` 与设备 LLM 合并必须使用 [`merge_llm_device_config()`](src/shuxin/voice/config.py)：**空字符串不得覆盖**已有 `model`/`base_url`/`api_key`。
- `/admin` 保存用户 LLM 时勿提交空的 `model`/`base_url`/`api_key`；否则可能让 WebSocket 路径退回全局默认模型（与 `devices.yaml` 不一致）。
- Voice 专用限额：`SHUXIN_VOICE_MAX_HISTORY`（默认 8）、`SHUXIN_VOICE_MAX_TOKENS`（默认 384）；CLI 默认 `max_history=30`（可配置）。LLM 超时：`SHUXIN_LLM_CONNECT_TIMEOUT_SECONDS`（默认 5）、`SHUXIN_LLM_TIMEOUT_SECONDS`（默认 60）。
- Voice 生产 TTS 为**火山复刻**（`volcengine-clone`）；`VOLCENGINE_TTS_API_KEY` / `VOLCENGINE_TTS_VOICE_TYPE` 经 compose 透传，改 `.env` 后须 `bash scripts/redeploy_docker.sh`。音色与人格由 Postgres `agents` 表 + `users.agent_id` 决定；设备 `metadata.mbti` 为盲盒语气差异。Admin：`/admin/api/agents`、`POST /admin/api/tts/preview`、设备 Tab「全部应用火山 TTS」。验收见 [`docs/VOICE_DEMO_MIN_TEST.md`](docs/VOICE_DEMO_MIN_TEST.md) §16；架构见 [`docs/VOICE_ARCHITECTURE.md`](docs/VOICE_ARCHITECTURE.md) §3.3。Edge/karen 仅 `scripts/generate_voiceover_candidates.py` 试听。
- **三层记忆（语音优先）**：短期 = `MemoryManager.short_term` 最近 N 轮原文；中期 = `shared_memory` 的 7 日 `rolling_summary` + 规则 `recent_topics`（每 `SHUXIN_SUMMARY_EVERY_N` 轮默认 5 + WebSocket 断线时异步小模型合并，见 `voice/memory_summary.py`）；长期 = Mem0+Qdrant（`SHUXIN_MEM0_ENABLED=1`，`core/memory.py` 每轮 `search`/`add`，`user_id` 从 `users/{id}/memory` 解析）或 legacy `facts.json`；陪伴插件状态仍在 Slot4。Docker：`requirements-voice-app.txt` + compose 服务 `qdrant`（本地 `QDRANT_HTTP_PORT` 默认 **6335**；**生产改回 6333** 见 [`docs/DEPLOY_SERVER.md`](docs/DEPLOY_SERVER.md)）。重连仅注入中期/长期，不回填最近原文。**音频附件**：`SHUXIN_AUDIO_RETENTION_HOURS`（默认 12）TTL 删磁盘 wav/mp3 并软删索引，文字事件保留；`compress_if_needed` 作 12h 内 quota 兜底，只压 input wav，不压对话。
- 中期摘要环境变量：`SHUXIN_SUMMARY_EVERY_N`、`SHUXIN_SUMMARY_MODEL`、`SHUXIN_SUMMARY_MAX_TOKENS`；合并后同步 `~/.shuxin/users/{user_id}/summaries/shared_memory.json` 供 `companion` `pre_llm_call` 读取。
- WebSocket 一轮对话：`stt/final` → `agent/thinking` → 流式 `agent/delta`（失败时先发 `agent/error` + `error_kind`）→ 分句 `tts/sentence_*` → `agent/reply` → `tts/stop`（含 `llm_ttft_ms`）。
- OpenAI 兼容流式 LLM（`core/llm.py`）：不 yield `reasoning_content`；过滤 `` 块；推理内容仅 DEBUG 日志 `[LLM-REASONING]`。测试 `tests/test_llm_stream_filter.py`。
- **括弧动作与流式 TTS 过滤约束**：在分句切句中（`_pop_speakable_segments`）必须具备括号感知，当字符处于未闭合的括弧（`()` 和 `（）`）内时，忽略切句标点符号以防止括号被截断。合成 TTS 时通过 `clean_action_text` 剥离括号内容以防语音读出动作；如果分句全是动作内容（过滤后文本为空），服务端跳过 TTS 调用与音频下发，但必须照常发送 `sentence_start`/`sentence_stop` 控制事件（携带原始括弧文本）以供硬件客户端触发对应动作。
- **百度地图 MCP（平台托管）**：`integrations/location/` 提供 `LocationToolProvider` 抽象；首版 `BaiduMcpLocationProvider` 走 `SHUXIN_MAP_MCP_URL` + `SHUXIN_BAIDU_MAP_AK`（Streamable HTTP）。**`docker-compose.yml` 须显式透传地图 env**（改 `.env` 后 `bash scripts/redeploy_docker.sh --skip-build`）。localhost 开发时 WebSocket `client_ip` 为私网/回环，须用出口公网 IP（`ip_resolve.py`）或 `SHUXIN_MAP_DEFAULT_REGION`；`user_profile.json` 的 location 为低置信推测，IP 成功时优先。未配置 AK 时不注册 tools。门控命中后才附 tools + function calling；模型不调 tool 时天气/POI 走服务端直调降级。Voice 默认 `SHUXIN_MAP_MAX_TOOL_ROUNDS=1`、`SHUXIN_MAP_MCP_TIMEOUT_SECONDS=3`。`map_ip_location` 仅服务端静默解析注入 Slot4，不暴露给 LLM。tool 轮 Voice 发 `agent/thinking`（`reason: map_lookup`）。
- 硬件接入（鉴权、STT/TTS 代理）：[`docs/VOICE_HARDWARE_QUICKSTART.md`](docs/VOICE_HARDWARE_QUICKSTART.md)、[`docs/VOICE_HARDWARE_INTEGRATION.md`](docs/VOICE_HARDWARE_INTEGRATION.md)、出厂验收 [`docs/FACTORY_ACCEPTANCE_HANDOFF.md`](docs/FACTORY_ACCEPTANCE_HANDOFF.md)；设备 Flash 提示音（16 kHz/16 kbps，`.ogg`+`.opus.bin`，脚本默认 `--format both` 并删 `_tmp`）：`data/device_assets/strings.zh-CN.json` + `scripts/generate_device_prompt_assets.py`，验收 [`docs/VOICE_DEMO_MIN_TEST.md`](docs/VOICE_DEMO_MIN_TEST.md) §18；语音故障排查：同文档 §10；协议字段：[`docs/VOICE_HARDWARE_WS_PROTOCOL.md`](docs/VOICE_HARDWARE_WS_PROTOCOL.md) §5。
- **出厂工厂验收**：`provisioned` 且未绑定设备 hello 走 `authenticate_device_for_factory()`，`factory_acceptance=true`；跳过 `ensure_session` 与 MBTI reveal；拦截 `listen`/`text_turn`；QA `POST /api/factory/verify` + WS `factory_verify`/`factory_verify_ack`。小程序入口：`POST /api/users/me` → `roles.factory_qa`，个人中心「工厂验收」；改 `apps/wechat-miniprogram` 后须 `scripts/wechat_miniprogram_dev.sh build`。Admin：`metadata.factory_role`（工厂 QA，勾选即存）≠ `users.enabled`（启用，改后点保存）。`factory_verify_logs` TTL：`SHUXIN_FACTORY_VERIFY_LOG_RETENTION_DAYS` 默认 15（`0` = 不删）。固件与 QA 排障见 [`docs/FACTORY_ACCEPTANCE_HANDOFF.md`](docs/FACTORY_ACCEPTANCE_HANDOFF.md)；测试 `tests/test_factory_verify.py`、`tests/test_users_me_api.py`。
- **MBTI 盲盒**：出厂 `mbti`+`sealed`；小程序 bind 揭晓→`locked`（响应 `mbti` 卡片；改 `apps/wechat-miniprogram` 源码后须 `scripts/wechat_miniprogram_dev.sh build` 重编译 `dist/*/mp-weixin`，否则微信工具仍是旧包无弹窗）；`sealed` 时 `/api/devices/my` 不返 `mbti`；首次硬件 TTS 播 `mbti_profiles.yaml` 的 `reveal_script`（`你好！绑定成功，我是 XX 型的初心。`；bind 时 WS 在线经 `voice_session_registry` 即时推，否则 hello 补播，`device_intro_played`）。Slot1 `SOUL.md` 不含 MBTI，设备气质由 Slot2 `identity` 承担；日常禁止 MBTI 类型码自我解释（用户主动问除外）。`_ensure_runtime` 须以 `agent is None` 初始化 STT/TTS/Agent（MBTI intro 可先预填 device）。小程序无解绑。详见 [`docs/DEVICE_MBTI_BLINDBOX_AND_MEMORY_PLAN.md`](docs/DEVICE_MBTI_BLINDBOX_AND_MEMORY_PLAN.md)、验收 [`docs/VOICE_DEMO_MIN_TEST.md`](docs/VOICE_DEMO_MIN_TEST.md) §9.2。
- **设备密钥加密**：批量制码/Admin 查看明文须 `.env` 配置 `SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY`（Fernet）并重部署；未配时 Admin 黄条 + 制码 API fail-fast。历史仅 hash 设备须重制码或 `rotate-secret`。

### 语音计费与宿主测试避坑约束

- **Pydantic/FastAPI Python 3.8 兼容性**：由于宿主机为 Python 3.8 环境，在 Pydantic 模型（如 `AnnouncementPayload`）以及 FastAPI 路由参数中声明类型时，**禁止使用现代 Union 类型（如 `int | None`）**。即使文件开头声明了 `from __future__ import annotations`，Pydantic 仍会在运行期评估时抛出 `TypeError`。必须使用 `typing.Optional[...]` 或 `typing.Union[...]`。
- **WebSocket 作用域约束**：`_VoiceWebSocketSession` 为顶层类。在其方法内部（如 `_process_turn`）**禁止直接引用局部 `app` 变量**（如 `app.state.billing`），否则会因作用域隔离引发 `NameError` 并被内部 Exception 静默捕获导致计费静默中止。必须在路由初始化时通过构造函数传入 `app` 实例并保存为 `self.app`，再通过 `self.app.state` 获取相关服务。
- **异步非阻塞计费设计**：对话 Turn 结束时的消费日志记录必须通过 `BillingService.record_usage_in_background` 异步非阻塞运行（采用 `asyncio.create_task`），任何计费数据库异常必须实现强隔离（Fault Isolation），绝不能影响或拖慢 STT -> LLM -> TTS 主语音循环的实时响应。
- **FastAPI TestClient 属性注入机制**：在编写集成测试（如 `tests/test_billing_api.py`）时，对 `app.state.repo` 等全局属性的 Mock 替换，**必须置于 `with TestClient(app) as client:` 上下文环境内部**。若在 context 外部注入，会在进入 `with` 块时被自动触发的 `startup` 事件处理器使用真实配置覆盖，导致 Mock 失效。

### 语音 Docker 运维脚本

- **Docker 内开发与 TTS 试听**（不在宿主机 pip 装包；新依赖须先批准）：[`docs/VOICE_DOCKER_WORKFLOW.md`](docs/VOICE_DOCKER_WORKFLOW.md)。
- `scripts/redeploy_docker.sh`：日常重部署；默认 `compose build`（Docker 层缓存）；`--skip-build` 仅重启；`--build` 全量 `--no-cache`。Compose 项目名固定为 `shuxin`（`docker compose -p shuxin`）。
- `scripts/export_pack.sh` / `scripts/import_deploy.sh`：环境迁移（代码、bind mount、`pg_dump`、Qdrant 卷；**不含** `.env` 与 Docker 镜像）。`import` 默认安装到**当前目录**，可用第二参数或 `INSTALL_DIR` 覆盖。
- 共用函数：`scripts/lib/docker_compose.sh`。
- 打包/导入验收：[`docs/VOICE_DEMO_MIN_TEST.md`](docs/VOICE_DEMO_MIN_TEST.md) §12–14。
