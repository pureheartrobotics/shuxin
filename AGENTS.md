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
