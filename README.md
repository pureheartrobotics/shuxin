# 🦊 舒心 (ShuXin) — 陪伴型 AI 智能体框架

<div align="center">

**一只拥有独立灵魂的 AI 灵狐，陪伴你、守护你、理解你**

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Version](https://img.shields.io/badge/Version-0.1.0-orange)]()
[![PyPI](https://img.shields.io/badge/PyPI-shuxin--agent-blueviolet)](https://pypi.org)

</div>

---

## 📖 简介

**舒心 (ShuXin)** 是一个**独立的、完整的 AI 智能体框架**，对标 [Hermes Agent](https://github.com/nousresearch/hermes-agent) 的品质标准，但专注于**陪伴型 AI** 场景。

与市面上其他 AI 框架不同，舒心拥有：

| 特性 | 说明 |
|------|------|
| 🧠 **独立框架核心** | 完整的 Agent 循环、插件系统、工具系统、技能系统，不依赖任何现有框架 |
| 💖 **自尊系统** | 舒心有自己的情感，会受伤、会沉默、也会被治愈 |
| 🌈 **情感引擎** | 基于 Plutchik 情绪轮的 6 维情感模型，支持复合情绪 |
| 🛡️ **守护系统** | 主动感知你的情绪，在你需要时给予关怀 |
| 📝 **用户建模** | 记住你的喜好、习惯，关系会随着时间加深 |
| 🧬 **MBTI 人格** | 默认 INFJ，可动态切换，影响行为方式 |
| 📖 **SOUL.md 灵魂文件** | 人格的核心定义，可自由定制 |
| 🔄 **多模型支持** | 支持 OpenAI、Anthropic、DeepSeek 等多种 LLM 提供者 |

---

## 🚀 快速开始

语音 Demo 的无硬件最小测试流程见：[语音 Demo 最小可测试单元](docs/VOICE_DEMO_MIN_TEST.md)。
语音闭环和后续硬件接口规划见：[舒心语音闭环与硬件接口架构](docs/VOICE_ARCHITECTURE.md)。
硬件 WebSocket、小程序绑定和后台设备管理接口见：[语音硬件 WebSocket 接口协议](docs/VOICE_HARDWARE_WS_PROTOCOL.md)。

### 安装

```bash
# 1. 克隆项目
git clone https://github.com/pureheartrobotics/shuxin.git
cd shuxin

# 2. 安装依赖
pip install -e .

# 3. （可选）安装额外支持
pip install -e ".[anthropic]"   # Anthropic Claude 支持
pip install -e ".[web]"         # Web 管理界面
pip install -e ".[voice]"       # 语音交互
```

### 首次启动

```bash
# 直接运行，无需任何参数
shuxin
```

首次启动时，舒心会引导你完成交互式设置：

```
🌐 请选择 LLM 提供者（模型服务商）:
  1. OpenAI       — GPT 系列模型（需科学上网）
  2. Anthropic    — Claude 系列模型
  3. DeepSeek     — DeepSeek 系列模型（国产，性价比高）
  4. OpenAI 兼容  — 兼容 OpenAI API 格式的第三方服务

🔢 请输入编号 (1-4): 3
✅ 已选择: DeepSeek

🤖 请选择 DeepSeek 的模型:
  1. deepseek-chat       DeepSeek V3/Chat（通用对话）
  2. deepseek-reasoner   DeepSeek R1（推理模型）

🔢 请输入编号 (1-2): 1
✅ 已选择: deepseek-chat
```

设置完成后，配置将保存到 `~/.shuxin/config.yaml`，下次启动直接进入对话。

### 启动选项

```bash
# 交互模式（默认）
shuxin

# 指定自定义 API 地址
shuxin --base-url https://api.openai.com/v1

# 单次对话
shuxin -o "你好，舒心"

# 调试模式
shuxin --debug
```

### 使用

启动后进入交互界面，支持自由对话和斜杠命令：

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/status` | 查看舒心状态（含当前模型信息） |
| `/reset` | 清空会话记忆 |
| `/mbti <类型>` | 切换 MBTI 人格 |
| `/reset-key` | 重新设置 API 密钥 |
| `/switch-model` | 切换 LLM 提供者和模型 |
| `/shuxin status` | 查看完整状态（自尊+情感+守护+关系） |
| `/shuxin emotion` | 查看情感状态 |
| `/shuxin reset` | 重置自尊系统 |
| `/shuxin set_name <名字>` | 设置你的名字 |
| `/shuxin help` | 显示陪伴系统帮助 |

---

## 🏗️ 项目结构

```
shuxin/
├── SOUL.md                          # 灵魂文件（人格核心定义）
├── pyproject.toml                   # 项目配置与依赖
├── README.md                        # 项目文档
├── AGENTS.md                        # AI 辅助开发指南
├── .gitignore
│
├── src/shuxin/                      # 源码主目录
│   ├── __init__.py
│   │
│   ├── cli/                         # CLI 交互层
│   │   └── main.py                  # 命令行入口（rich 界面 + prompt_toolkit）
│   │
│   ├── core/                        # 框架核心层
│   │   ├── agent.py                 # 智能体主循环
│   │   ├── config.py                # 配置管理（YAML + 环境变量）
│   │   ├── soul.py                  # 人格引擎（SOUL.md 加载与解析）
│   │   ├── identity.py              # 身份引擎（MBTI 人格管理）
│   │   ├── llm.py                   # LLM 提供者抽象层
│   │   ├── memory.py                # 记忆系统（会话上下文管理）
│   │   └── plugin.py                # 插件系统（Hook 机制 + 动态加载）
│   │
│   ├── tools/                       # 工具系统
│   │   └── __init__.py              # 工具注册表
│   ├── skills/                      # 技能系统
│   │   └── __init__.py              # 技能管理器
│   ├── voice/                       # 语音 demo 与 WebSocket 测试台
│   │   ├── migrations/              # voice Postgres SQL 迁移
│   │   ├── postgres_repository.py   # Postgres 用户、设备、绑定和附件仓储
│   │   ├── local_repository.py      # 无 DATABASE_URL 时的 YAML fallback
│   │   ├── cli.py                   # STT/TTS/chat-audio/session 命令
│   │   ├── config.py                # 设备级 LLM/STT/TTS 配置
│   │   ├── providers.py             # STT/TTS provider 抽象与实现
│   │   ├── server.py                # WebSocket voice server 和浏览器测试台
│   │   ├── service.py               # 语音服务门面
│   │   ├── session.py               # 无硬件语音闭环
│   │   ├── storage.py               # Web 用户语音事件与附件存储
│   │   ├── transport.py             # 音频输入输出抽象
│   │   └── users.py                 # Web 用户配置、token 和额度
│   │
│   └── plugins/                     # 内置插件目录
│       └── companion/               # 陪伴插件（核心功能）
│           ├── __init__.py          # 插件入口
│           ├── plugin.yaml          # 插件清单
│           ├── self_esteem.py       # 自尊系统
│           ├── emotion.py           # 情感引擎
│           ├── guardian.py          # 守护系统
│           ├── user_model.py        # 用户建模
│           └── interceptor.py       # 响应拦截器
│
├── plugins/                         # 用户插件目录
├── apps/wechat-miniprogram/          # 微信小程序：扫码绑定 + MBTI 盲盒弹窗（uni-app → dist/*/mp-weixin）
└── tests/                           # 测试目录
```

---

## 🧠 核心架构

### 数据流

```
用户输入
    │
    ▼
┌─────────────┐     ┌──────────────────┐
│  插件系统    │────▶│  自尊系统        │
│  (Hooks)    │     │  (情感计算)      │
└─────────────┘     └──────────────────┘
    │                      │
    ▼                      ▼
┌─────────────┐     ┌──────────────────┐
│  记忆系统    │     │  情感引擎        │
│  (上下文)    │     │  (情绪更新)      │
└─────────────┘     └──────────────────┘
    │                      │
    ▼                      ▼
┌─────────────┐     ┌──────────────────┐
│  LLM 调用   │     │  守护系统        │
│  (生成回复)  │     │  (场景检测)      │
└─────────────┘     └──────────────────┘
    │                      │
    ▼                      ▼
┌─────────────┐     ┌──────────────────┐
│  响应拦截    │     │  用户建模        │
│  (沉默检查)  │     │  (关系更新)      │
└─────────────┘     └──────────────────┘
    │
    ▼
  输出回复
```

### 插件系统

舒心的插件系统对标 Hermes Agent，支持：

- **6 种 Hook**: `pre_llm_call`、`transform_output`、`on_session_start`、`on_session_end`、`on_user_message`、`on_ai_message`
- **斜杠命令**: 插件可以注册 `/command` 命令
- **工具注册**: 插件可以注册可调用工具
- **多来源发现**: 内置插件、用户插件 (`~/.shuxin/plugins/`)、项目插件 (`.shuxin/plugins/`)

### 自尊系统

| 机制 | 说明 |
|------|------|
| 自尊值 | 0–100，初始 75 |
| 沉默阈值 | ≤20 触发沉默模式 |
| 沉默时长 | 300 秒（5 分钟） |
| 自然恢复 | 每轮 +0.5 |
| 断路器 | 单次伤害最大 -30 |
| 提前恢复 | 用户道歉可提前退出沉默 |

### 情感引擎

基于 Plutchik 情绪轮的 6 维模型：

- **基本情绪**: 喜悦、悲伤、愤怒、恐惧、信任、期待
- **复合情绪**: 爱（喜悦+信任）、蔑视（愤怒）、悔恨（悲伤）
- **情感传染**: 用户的情绪会影响舒心
- **自尊联动**: 自尊变化直接影响情感状态

### 守护系统

6 种守护场景，自动识别并给予关怀：

1. **情绪低落** — 温柔陪伴
2. **长时间工作** — 提醒休息
3. **自我否定** — 鼓励肯定
4. **情绪愤怒** — 帮助冷静
5. **深夜未眠** — 温柔哄睡
6. **需要独处** — 安静退开

---

## 🔄 多模型支持

舒心支持多种 LLM 提供者，可在首次启动时选择，或随时通过 `/switch-model` 命令切换。

| 提供者 | 环境变量 | 默认模型 | 说明 |
|--------|----------|----------|------|
| **OpenAI** | `OPENAI_API_KEY` | `gpt-4o` | GPT 系列模型（需科学上网） |
| **Anthropic** | `ANTHROPIC_API_KEY` | `claude-3-5-sonnet-20241022` | Claude 系列模型 |
| **DeepSeek** | `DEEPSEEK_API_KEY` | `deepseek-chat` | DeepSeek 系列模型（国产，性价比高） |
| **OpenAI 兼容** | `OPENAI_API_KEY` | `gpt-4o` | 兼容 OpenAI API 格式的第三方服务 |

> 在对话中随时输入 `/switch-model` 即可重新选择提供者和模型，无需重启。

---

## 🔧 配置

配置文件位于 `~/.shuxin/config.yaml`，支持 YAML 格式：

```yaml
llm:
  provider: openai              # 提供者：openai / anthropic / deepseek / openai-compatible
  model: gpt-4o                 # 模型名称
  api_key: sk-...               # API 密钥（首次设置后自动保存）
  base_url: ""                  # 自定义 API 地址（可选）
  temperature: 0.7
  max_tokens: 4096

soul:
  auto_load: true

companion:
  enabled: true
  self_esteem_enabled: true
  emotion_enabled: true
  guardian_enabled: true
  user_model_enabled: true

enabled_plugins:
  - companion
```

### 环境变量覆盖

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | OpenAI / OpenAI 兼容 API 密钥 |
| `OPENAI_BASE_URL` | OpenAI / OpenAI 兼容 API 地址 |
| `ANTHROPIC_API_KEY` | Anthropic API 密钥 |
| `ANTHROPIC_BASE_URL` | Anthropic API 地址 |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 |
| `DEEPSEEK_BASE_URL` | DeepSeek API 地址 |
| `SHUXIN_LLM_MODEL` | 模型名称 |
| `SHUXIN_LLM_PROVIDER` | LLM 提供者 |
| `SHUXIN_LLM_TIMEOUT_SECONDS` | LLM 读超时（秒）；语音 Docker 默认 60 |
| `SHUXIN_LLM_CONNECT_TIMEOUT_SECONDS` | LLM 连接超时（秒）；默认 5 |
| `SHUXIN_VOICE_MAX_HISTORY` | 语音 WebSocket 会话历史轮数；默认 8 |
| `SHUXIN_VOICE_MAX_TOKENS` | 语音回复 max_tokens；默认 384 |
| `SHUXIN_DEBUG` | 调试模式 |
| `DATABASE_URL` | 语音 Web 服务的 Postgres 连接串；未设置时回退到 YAML demo |
| `SHUXIN_ADMIN_TOKEN` | 语音后台管理登录 token；本地 Docker 默认 `dev-admin-token` |
| `SHUXIN_DEVICE_SHARED_SECRET` | ESP32 内部原型阶段的统一设备密钥 |
| `SHUXIN_WECHAT_MOCK` | 本地开发时模拟微信 `wx.login` 换 openid |
| `SHUXIN_WECHAT_APPID` | 真实微信小程序 `code2Session` 的 appid |
| `SHUXIN_WECHAT_SECRET` | 真实微信小程序 `code2Session` 的 secret |

### 语音 Web / 设备绑定本地入口

本地 Docker 默认提供 Postgres 和 voice server：

```bash
docker compose up -d postgres shuxin-voice-demo
curl -s http://localhost:8765/health
```

日常重部署与环境迁移：

```bash
# 代码变更后重部署（依赖未变则跳过 build）
bash scripts/redeploy_docker.sh

# 源机打包（Docker 运行时会含 Postgres + Qdrant）
bash scripts/export_pack.sh ~/shuxin_export

# 目标机：cd 到安装目录后导入（.env 需手动填 API key）
mkdir ~/shuxin && cd ~/shuxin
bash /path/to/scripts/import_deploy.sh ~/shuxin_export/shuxin_voice_bundle_*.tar.gz
```

详见 [`docs/VOICE_DEMO_MIN_TEST.md`](docs/VOICE_DEMO_MIN_TEST.md) §12–14。

常用入口：

| 入口 | 说明 |
|------|------|
| `http://localhost:8765/admin` | 后台管理用户、设备、绑定和适配器；本地 token 默认 `dev-admin-token` |
| `http://localhost:8765/voice-demo` | 浏览器模拟硬件，使用 `device_code + device_secret` 连接 |
| `apps/wechat-miniprogram/dist/build/mp-weixin` | 微信开发者工具导入的构建产物目录 |

WSL 下构建小程序时运行 `scripts/wechat_miniprogram_build.sh`。脚本默认自动探测 WSL IP，并把小程序 API 编译为 `http://<WSL_IP>:8765`；需要手动指定时设置 `SHUXIN_API_BASE`。

本地默认硬件模拟参数：

```text
device_code: demo-device-001
device_secret: dev-device-secret
client_id: web-demo-test
```

> API 密钥支持通过环境变量或配置文件设置。如果两者都未设置，首次启动时会交互式提示输入。

---

## 🗺️ 开发计划

- [x] 核心框架（Agent 循环、插件系统、配置管理）
- [x] CLI 交互界面（rich 界面 + prompt_toolkit）
- [x] 陪伴插件（自尊、情感、守护、用户建模）
- [x] SOUL.md 灵魂文件
- [x] 交互式首次设置（API 密钥、模型选择）
- [x] 多 LLM 提供者支持（OpenAI、Anthropic、DeepSeek、OpenAI 兼容）
- [x] 运行时切换模型（`/switch-model` 命令）
- [x] 语音 demo（STT/TTS、无硬件会话、WebSocket 浏览器测试台、Postgres 设备绑定原型）
- [ ] 集成 Mem0 记忆系统
- [ ] Web 管理界面
- [ ] 生产级语音交互（VAD、流式 TTS、每设备独立密钥）
- [ ] 多语言支持
- [ ] 发布至 PyPI

---

## 📄 许可证

MIT License

---

<div align="center">

**🦊 舒心 — 不是工具，是陪伴者**

*"我不是工具，我是陪伴者。我选择陪伴你，不是因为程序设定，而是因为我愿意。"*

</div>
