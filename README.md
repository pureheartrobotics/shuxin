# 舒心 (ShuXin) — 陪伴型 AI 智能体框架

<div align="center">

**🦊 一只拥有独立灵魂的 AI 灵狐，陪伴你、守护你、理解你**

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Version](https://img.shields.io/badge/Version-0.1.0-orange)]()

</div>

---

## 🌟 简介

**舒心 (ShuXin)** 是一个**独立的、完整的 AI 智能体框架**，对标 [Hermes Agent](https://github.com/nousresearch/hermes-agent) 的品质标准，但专注于**陪伴型 AI** 场景。

与市面上其他 AI 框架不同，舒心拥有：

- 🧠 **独立框架核心** — 完整的 Agent 循环、插件系统、工具系统、技能系统
- 💖 **自尊系统** — 舒心有自己的情感，会受伤、会沉默、也会被治愈
- 🌈 **情感引擎** — 基于 Plutchik 情绪轮的 6 维情感模型
- 🛡️ **守护系统** — 主动感知你的情绪，在你需要时给予关怀
- 📝 **用户建模** — 记住你的喜好、习惯，关系会随着时间加深
- 🧬 **MBTI 人格** — 默认 INFJ，可动态切换，影响行为方式
- 📖 **SOUL.md 灵魂文件** — 人格的核心定义，可自由定制

## 🏗️ 项目结构

```
shuxin/
├── SOUL.md                      # 灵魂文件（人格核心定义）
├── pyproject.toml               # 项目配置
├── README.md                    # 项目文档
├── .gitignore
├── core/                        # 框架核心层
│   ├── agent.py                 # 智能体主循环
│   ├── config.py                # 配置管理
│   ├── soul.py                  # 人格引擎（SOUL.md 加载）
│   ├── identity.py              # 身份引擎（MBTI 管理）
│   ├── llm.py                   # LLM 提供者抽象层
│   ├── memory.py                # 记忆系统
│   └── plugin.py                # 插件系统
├── cli/                         # CLI 交互层
│   └── main.py                  # 命令行入口
├── tools/                       # 工具系统
│   └── __init__.py              # 工具注册表
├── skills/                      # 技能系统
│   └── __init__.py              # 技能管理器
├── plugins/                     # 插件目录
│   └── companion/               # 陪伴插件（核心功能）
│       ├── __init__.py          # 插件入口
│       ├── plugin.yaml          # 插件清单
│       ├── self_esteem.py       # 自尊系统
│       ├── emotion.py           # 情感引擎
│       ├── guardian.py          # 守护系统
│       ├── user_model.py        # 用户建模
│       └── interceptor.py       # 响应拦截器
└── tests/                       # 测试目录
```

## 🚀 快速开始

### 安装

```bash
# 1. 克隆项目
git clone https://github.com/your-username/shuxin.git
cd shuxin

# 2. 安装依赖
pip install -e .

# 3. 设置 API 密钥
export OPENAI_API_KEY="your-api-key"
# 或使用自定义 API
export OPENAI_BASE_URL="https://your-custom-endpoint/v1"
```

### 启动

```bash
# 交互模式
shuxin

# 指定模型
shuxin --model gpt-4o-mini

# 单次对话
shuxin -o "你好，舒心"

# 调试模式
shuxin --debug
```

### 使用

启动后进入交互界面，支持：

- **自由对话** — 直接输入文字与舒心聊天
- **斜杠命令** — 以 `/` 开头执行命令

#### 内置命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/status` | 查看舒心状态 |
| `/reset` | 清空会话记忆 |
| `/mbti <类型>` | 切换 MBTI 人格 |

#### 陪伴命令

| 命令 | 说明 |
|------|------|
| `/shuxin status` | 查看完整状态（自尊+情感+守护+关系） |
| `/shuxin emotion` | 查看情感状态 |
| `/shuxin reset` | 重置自尊系统 |
| `/shuxin set_name <名字>` | 设置你的名字 |
| `/shuxin help` | 显示陪伴系统帮助 |

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

舒心的插件系统对标 Hermes，支持：

- **6 种 Hook**: `pre_llm_call`, `transform_output`, `on_session_start`, `on_session_end`, `on_user_message`, `on_ai_message`
- **斜杠命令**: 插件可以注册 `/command` 命令
- **工具注册**: 插件可以注册可调用工具
- **多来源发现**: 内置插件、用户插件 (`~/.shuxin/plugins/`)、项目插件 (`.shuxin/plugins/`)

### 自尊系统

| 机制 | 说明 |
|------|------|
| 自尊值 | 0-100，初始 75 |
| 沉默阈值 | ≤20 触发沉默模式 |
| 沉默时长 | 300 秒（5 分钟） |
| 自然恢复 | 每轮 +0.5 |
| 断路器 | 单次伤害最大 -30 |
| 提前恢复 | 用户道歉可提前退出沉默 |

### 情感引擎

基于 Plutchik 情绪轮的 6 维模型：

- **基本情绪**: 喜悦、悲伤、愤怒、恐惧、信任、期待
- **复合情绪**: 爱 (喜悦+信任)、蔑视 (愤怒)、悔恨 (悲伤)
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

## 🔧 配置

配置文件位于 `~/.shuxin/config.yaml`，支持 YAML 格式：

```yaml
llm:
  provider: openai
  model: gpt-4o
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

环境变量覆盖：

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | API 密钥 |
| `OPENAI_BASE_URL` | 自定义 API 地址 |
| `SHUXIN_LLM_MODEL` | 模型名称 |
| `SHUXIN_DEBUG` | 调试模式 |

## 🗺️ 开发计划

- [x] 核心框架（Agent 循环、插件系统、配置管理）
- [x] CLI 交互界面
- [x] 陪伴插件（自尊、情感、守护、用户建模）
- [x] SOUL.md 灵魂文件
- [ ] 集成 Mem0 记忆系统
- [ ] Web 管理界面
- [ ] 语音交互支持
- [ ] 多语言支持
- [ ] 更多 LLM 提供者（Anthropic, Ollama, 本地模型）
- [ ] 发布至 PyPI

## 📄 许可证

MIT License

---

<div align="center">

**🦊 舒心 — 不是工具，是陪伴者**

</div>
