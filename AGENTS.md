# 舒心 (ShuXin) — 陪伴型 AI 智能体框架

## 项目概述

舒心是一个**独立的 AI 智能体框架**，对标 Hermes Agent 的品质标准，专注于陪伴型 AI 场景。

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
5. **自尊为核心** — 自尊系统是舒心的"灵魂"，所有子系统围绕它运转

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

舒心当前是一个 Python `src` layout 项目，主入口在 CLI，核心协调者是 `core/agent.py`。

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
- 硬件接入（鉴权、STT/TTS 代理）：[`docs/VOICE_HARDWARE_QUICKSTART.md`](docs/VOICE_HARDWARE_QUICKSTART.md)、[`docs/VOICE_HARDWARE_INTEGRATION.md`](docs/VOICE_HARDWARE_INTEGRATION.md)；设备 Flash 提示音：`data/device_assets/strings.zh-CN.json` + `scripts/generate_device_prompt_assets.py`；语音故障排查：[`docs/VOICE_DEMO_MIN_TEST.md`](docs/VOICE_DEMO_MIN_TEST.md) §10；协议字段：[`docs/VOICE_HARDWARE_WS_PROTOCOL.md`](docs/VOICE_HARDWARE_WS_PROTOCOL.md) §5。

### 语音 Docker 运维脚本

- **Docker 内开发与 TTS 试听**（不在宿主机 pip 装包；新依赖须先批准）：[`docs/VOICE_DOCKER_WORKFLOW.md`](docs/VOICE_DOCKER_WORKFLOW.md)。
- `scripts/redeploy_docker.sh`：日常重部署；Compose 项目名固定为 `shuxin`（`docker compose -p shuxin`）。
- `scripts/export_pack.sh` / `scripts/import_deploy.sh`：环境迁移（代码、bind mount、`pg_dump`、Qdrant 卷；**不含** `.env` 与 Docker 镜像）。`import` 默认安装到**当前目录**，可用第二参数或 `INSTALL_DIR` 覆盖。
- 共用函数：`scripts/lib/docker_compose.sh`。
- 打包/导入验收：[`docs/VOICE_DEMO_MIN_TEST.md`](docs/VOICE_DEMO_MIN_TEST.md) §12–14。
