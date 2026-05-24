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

- `tools` 已有注册表和 OpenAI tool schema 转换能力，但尚未接入 `Agent` 的 LLM 调用链。
- `skills` 已有 `SKILL.md` 发现和解析框架，但尚未注入 `Agent` 系统提示或命令流程。
- 仓库当前没有 `tests/` 目录，`pyproject.toml` 已预留 pytest 配置。
- README 中提到的部分目录如 `providers/`、`locales/`、`assets/` 当前尚未在源码树中实现。
