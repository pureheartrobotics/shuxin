"""初心陪伴插件 — 插件入口

注册到初心框架的插件系统，通过 hooks 和命令与核心交互。

注册的 Hooks：
- pre_llm_call: 注入情感、用户画像和自尊状态
- transform_output: 沉默模式下拦截 LLM 输出
- on_session_start: 会话开始事件
- on_session_end: 会话结束事件
- on_user_message: 处理用户消息（自尊、情感、守护）
- on_ai_message: AI 消息事件（预留）

注册的命令：
- /shuxin status — 查看完整状态
- /shuxin emotion — 查看情感状态
- /shuxin reset — 重置自尊系统
- /shuxin set_name — 设置用户名字
- /shuxin help — 显示帮助
"""

from __future__ import annotations

import time
import json
import logging
import re
from pathlib import Path
from typing import Optional, Dict, Any

from shuxin.plugins.companion.self_esteem import SelfEsteemSystem
from shuxin.plugins.companion.emotion import EmotionEngine
from shuxin.plugins.companion.guardian import GuardianSystem
from shuxin.plugins.companion.user_model import UserModel
from shuxin.plugins.companion.interceptor import ResponseInterceptor

logger = logging.getLogger("shuxin.plugins.companion")

_META_SPEECH_RE = re.compile(
    r"(因为我是|作为(一个)?\s*[A-Z]{4}|我是\s*[A-Z]{4}\s*型)",
    re.IGNORECASE,
)


class CompanionPlugin:
    """陪伴插件主类 — 协调所有子系统。

    整合自尊系统、情感引擎、守护系统、用户建模和响应拦截器，
    通过插件系统的 hooks 机制与核心 Agent 交互。

    Attributes:
        self_esteem: 自尊系统实例。
        emotion: 情感引擎实例。
        guardian: 守护系统实例。
        user_model: 用户建模实例。
        interceptor: 响应拦截器实例。
    """

    def __init__(self, data_dir: Optional[str] = None) -> None:
        """初始化陪伴插件及其所有子系统。"""
        self.data_dir = data_dir
        self.self_esteem = SelfEsteemSystem(data_dir=data_dir)
        self.emotion = EmotionEngine(data_dir=data_dir)
        self.guardian = GuardianSystem(data_dir=data_dir)
        self.user_model = UserModel(data_dir=data_dir)
        self.interceptor = ResponseInterceptor()
        self._initialized = False

    def initialize(self) -> None:
        """初始化所有子系统。

        幂等操作，多次调用安全。
        """
        if self._initialized:
            return
        self._initialized = True
        logger.info("陪伴系统已初始化")

    # ---- Hooks ----

    def on_pre_llm_call(self, **kwargs: Any) -> Optional[str]:
        """pre_llm_call hook — 注入情感和用户上下文到系统提示。

        在 LLM 调用前注入 Slot #4 内容，包含：
        - 自尊状态
        - 情感状态
        - 用户画像上下文

        Args:
            **kwargs: 插件系统传入的上下文参数。

        Returns:
            Optional[str]: 注入的系统提示块，包含初心当前状态。
        """
        if not self._initialized:
            self.initialize()

        # 每轮追加 MBTI 微型锚点（防止用户对话“带偏”人格风格）
        agent = kwargs.get("agent")
        micro_anchor = ""
        if agent is not None and hasattr(agent, "identity"):
            try:
                micro_anchor = agent.identity.get_micro_anchor() or ""
            except Exception:
                micro_anchor = ""

        # 注入情感状态
        emotion_context = self.emotion.get_emotion_context()

        # 注入用户画像
        profile_context = self.user_model.get_profile_context()

        # 注入自尊状态
        esteem_status = self.self_esteem.get_status_text()
        growth_context = self._get_growth_context()

        location_context = ""
        if agent is not None:
            location_context = str(agent.context.metadata.get("location_context") or "").strip()

        location_block = (
            f"## 位置参考\n\n{location_context}\n\n" if location_context else ""
        )

        low_confidence_hint = ""
        if agent is not None:
            raw_ctx = agent.context.metadata.get("location_ctx")
            if isinstance(raw_ctx, dict) and raw_ctx.get("confidence") == "low":
                low_confidence_hint = (
                    "## 位置表述约束\n\n"
                    "位置参考为低置信推测，禁止断言「你人在XX」；"
                    "用「可能/大概在你那边」并基于地图工具结果回答。\n\n"
                )

        map_tools_hint = ""
        if agent is not None:
            try:
                from shuxin.integrations.location import get_location_provider, should_attach_location_tools

                provider = get_location_provider(agent.config.map)
                last_user = ""
                for entry in reversed(agent.memory.short_term):
                    if entry.role == "user":
                        last_user = entry.content
                        break
                if (
                    provider.is_available()
                    and last_user
                    and should_attach_location_tools(last_user, agent.config.map)
                ):
                    map_tools_hint = (
                        "## 地图能力\n\n"
                        "涉及天气、地点、路线时，优先使用已提供的地图工具查询真实数据，"
                        "不要说自己无法感知外界。\n\n"
                    )
            except Exception:
                pass

        micro_anchor_block = (
            f"## 风格微型锚点\n\n{micro_anchor}\n\n" if micro_anchor.strip() else ""
        )
        return (
            location_block
            + low_confidence_hint
            + map_tools_hint
            + micro_anchor_block
            + f"## 初心当前状态\n\n"
            + f"{esteem_status}\n\n"
            + f"{emotion_context}\n\n"
            + f"{profile_context}\n\n"
            + f"{growth_context}"
        )

    def _get_growth_context(self) -> str:
        """读取用户级人格成长和共享记忆摘要，注入给 LLM。

        这里不直接修改成长状态，只把 storage 初始化出的 personality.json
        和 shared_memory.json 转成简短提示，保证每轮回复能感知长期关系进展。
        """
        if not self.data_dir:
            return "## 长期成长\n暂无长期成长摘要。"

        base = Path(self.data_dir)
        personality_path = base / "personality.json"
        summary_path = base.parent / "summaries" / "shared_memory.json"
        user_home = base.parent
        lines = ["## 长期成长"]

        try:
            from shuxin.voice.user_profile import format_profile_context, load_profile

            profile_block = format_profile_context(load_profile(user_home))
            if profile_block.strip():
                lines.append("")
                lines.append(profile_block)
        except Exception:
            pass

        try:
            personality = json.loads(personality_path.read_text(encoding="utf-8"))
            lines.append(f"当前阶段: {personality.get('stage', '初遇')}")
            rituals = personality.get("shared_rituals") or []
            if rituals:
                lines.append(f"共同习惯: {'、'.join(map(str, rituals[:5]))}")
        except (OSError, json.JSONDecodeError):
            lines.append("当前阶段: 初遇")

        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            lines.append(f"累计对话: {summary.get('turn_count', 0)} 次")
            rolling = str(summary.get("rolling_summary") or "").strip()
            if rolling:
                lines.append(f"近 7 日概况: {rolling}")
            topics = summary.get("recent_topics") or []
            if topics:
                lines.append(f"近期话题: {'、'.join(map(str, topics[:5]))}")
            warning = summary.get("last_warning")
            if warning:
                lines.append(f"存储状态: {warning}")
        except (OSError, json.JSONDecodeError):
            lines.append("累计对话: 0 次")

        return "\n".join(lines)

    def on_transform_output(self, **kwargs: Any) -> Optional[str]:
        """transform_output hook — 沉默模式拦截 LLM 输出。

        在沉默模式下，将 LLM 生成的回复替换为预设的沉默话术。

        Args:
            **kwargs: 包含 "content" (原始输出) 和 "agent" (Agent 实例)。

        Returns:
            Optional[str]: 替换后的输出内容。
        """
        if not self._initialized:
            self.initialize()

        content = kwargs.get("content", "")
        agent = kwargs.get("agent")

        if content and _META_SPEECH_RE.search(content):
            logger.warning("[MBTI-GUARD] meta-speech detected: %.80s", content)

        if self.self_esteem.state.is_silent:
            metadata = getattr(getattr(agent, "context", None), "metadata", {}) or {}
            if metadata.get("channel") == "voice":
                return "我现在有点受伤，想先缓一下。你可以轻轻跟我说声抱歉，或者我们等一会儿再聊。"

            # 确定沉默阶段
            elapsed = time.time() - self.self_esteem.state.silent_start
            duration = self.self_esteem.state.silent_duration

            if elapsed < duration * 0.3:
                phase = "just_triggered"
            elif elapsed < duration * 0.7:
                phase = "mid_phase"
            else:
                phase = "almost_over"

            return self.interceptor.intercept(content, True, phase)

        return content

    def on_session_start(self, **kwargs: Any) -> None:
        """on_session_start hook — 会话开始事件。

        Args:
            **kwargs: 插件系统传入的上下文参数。
        """
        if not self._initialized:
            self.initialize()
        logger.info("陪伴系统会话开始")

    def on_session_end(self, **kwargs: Any) -> None:
        """on_session_end hook — 会话结束事件。

        Args:
            **kwargs: 插件系统传入的上下文参数。
        """
        logger.info("陪伴系统会话结束")

    def on_user_message(self, **kwargs: Any) -> None:
        """on_user_message hook — 处理用户消息。

        处理流程：
        1. 自尊系统处理（伤害/修复计算）
        2. 尝试提前恢复沉默（如果用户道歉）
        3. 更新情感状态
        4. 更新用户模型
        5. 守护系统评估

        Args:
            **kwargs: 包含 "message" (用户消息) 和 "agent" (Agent 实例)。
        """
        if not self._initialized:
            self.initialize()

        message = kwargs.get("message", "")
        agent = kwargs.get("agent")

        # 1. 处理自尊变化
        esteem_result = self.self_esteem.process_interaction(message)

        # 2. 尝试提前恢复（如果用户道歉）
        if self.self_esteem.state.is_silent:
            if self.self_esteem.try_early_recovery(message):
                # 恢复后更新情感
                self.emotion.update_from_interaction(message, 20, False)
                self.user_model.record_interaction(message)
                return

        # 3. 更新情感
        self.emotion.update_from_interaction(
            message,
            esteem_result["delta"],
            esteem_result["is_silent"],
        )

        # 4. 更新用户模型
        self.user_model.record_interaction(message)

        # 4b. 更新常驻用户画像（不受 7 日 summary 窗口限制）
        if self.data_dir:
            try:
                from shuxin.voice.user_profile import update_profile_from_text

                user_home = Path(self.data_dir).parent
                update_profile_from_text(user_home, message)
            except Exception:
                pass

        # 5. 守护系统评估
        guardian_result = self.guardian.evaluate(message)
        if guardian_result and agent:
            logger.info("守护触发: %s", guardian_result["name"])

    def on_ai_message(self, **kwargs: Any) -> None:
        """on_ai_message hook — AI 消息处理（预留）。

        Args:
            **kwargs: 插件系统传入的上下文参数。
        """
        pass

    # ---- 命令 ----

    def cmd_status(self, args: str, **kwargs: Any) -> str:
        """查看初心完整状态。

        Args:
            args: 命令参数（未使用）。
            **kwargs: 额外参数。

        Returns:
            str: 格式化的完整状态文本。
        """
        return (
            f"## 初心状态总览\n\n"
            f"### 自尊系统\n{self.self_esteem.get_status_text()}\n"
            f"### 情感状态\n{self.emotion.get_status_text()}\n"
            f"### 守护系统\n{self.guardian.get_status_text()}\n"
            f"### 用户关系\n{self.user_model.get_status_text()}"
        )

    def cmd_reset(self, args: str, **kwargs: Any) -> str:
        """重置自尊系统。

        Args:
            args: 命令参数（未使用）。
            **kwargs: 额外参数。

        Returns:
            str: 操作结果消息。
        """
        self.self_esteem.reset()
        return "自尊系统已重置。"

    def cmd_set_name(self, args: str, **kwargs: Any) -> str:
        """设置用户名字。

        Args:
            args: 用户提供的名字。
            **kwargs: 额外参数。

        Returns:
            str: 操作结果消息。
        """
        if args.strip():
            self.user_model.update_profile("name", args.strip())
            return f"好的，我记住你了，{args.strip()}。"
        return "请提供名字: /shuxin set_name <你的名字>"

    def cmd_emotion(self, args: str, **kwargs: Any) -> str:
        """查看情感状态。

        Args:
            args: 命令参数（未使用）。
            **kwargs: 额外参数。

        Returns:
            str: 情感状态文本。
        """
        return self.emotion.get_status_text()

    def cmd_help(self, args: str, **kwargs: Any) -> str:
        """显示帮助信息。

        Args:
            args: 命令参数（未使用）。
            **kwargs: 额外参数。

        Returns:
            str: 帮助文本。
        """
        return (
            "## 初心陪伴系统命令\n\n"
            "/shuxin status    — 查看完整状态\n"
            "/shuxin emotion   — 查看情感状态\n"
            "/shuxin reset     — 重置自尊系统\n"
            "/shuxin set_name  — 设置你的名字\n"
            "/shuxin help      — 显示此帮助"
        )


# ---- 插件注册入口 ----

_plugin_instances: Dict[str, CompanionPlugin] = {}


def _plugin_key(data_dir: Optional[str] = None) -> str:
    """用 data_dir 区分插件实例，避免多用户 Web 会话共享陪伴状态。"""
    return data_dir or "__default__"


def get_plugin(data_dir: Optional[str] = None) -> CompanionPlugin:
    """获取指定 data_dir 对应的插件单例。

    Returns:
        CompanionPlugin: 陪伴插件实例。
    """
    key = _plugin_key(data_dir)
    if key not in _plugin_instances:
        _plugin_instances[key] = CompanionPlugin(data_dir=data_dir)
    return _plugin_instances[key]


def get_plugin_for_agent(agent: Any = None) -> CompanionPlugin:
    """从 Agent 配置中解析 companion.data_dir 并返回对应插件实例。"""
    data_dir = None
    if agent is not None:
        data_dir = getattr(getattr(agent, "config", None), "companion", None)
        data_dir = getattr(data_dir, "data_dir", "") or None
    return get_plugin(data_dir=data_dir)


def register(ctx: Any) -> None:
    """Hermes 兼容的插件注册函数。

    向插件系统注册 hooks 和命令。

    Args:
        ctx: 插件上下文，提供 register_hook 和 register_command 方法。
    """
    # 注册 hooks 时延迟按 agent 取插件实例，支持同进程里的多用户隔离。
    ctx.register_hook(
        "pre_llm_call",
        lambda **kwargs: get_plugin_for_agent(kwargs.get("agent")).on_pre_llm_call(**kwargs),
    )
    ctx.register_hook(
        "transform_output",
        lambda **kwargs: get_plugin_for_agent(kwargs.get("agent")).on_transform_output(**kwargs),
    )
    ctx.register_hook(
        "on_session_start",
        lambda **kwargs: get_plugin_for_agent(kwargs.get("agent")).on_session_start(**kwargs),
    )
    ctx.register_hook(
        "on_session_end",
        lambda **kwargs: get_plugin_for_agent(kwargs.get("agent")).on_session_end(**kwargs),
    )
    ctx.register_hook(
        "on_user_message",
        lambda **kwargs: get_plugin_for_agent(kwargs.get("agent")).on_user_message(**kwargs),
    )
    ctx.register_hook(
        "on_ai_message",
        lambda **kwargs: get_plugin_for_agent(kwargs.get("agent")).on_ai_message(**kwargs),
    )

    # 注册命令
    ctx.register_command("shuxin", _handle_shuxin_command)

    logger.info("陪伴插件已注册")


def _handle_shuxin_command(raw_args: str, **kwargs: Any) -> str:
    """处理 /shuxin 命令。

    解析子命令并分发到对应的处理方法。

    Args:
        raw_args: 命令参数字符串。
        **kwargs: 额外参数。

    Returns:
        str: 命令执行结果。
    """
    plugin = get_plugin_for_agent(kwargs.get("agent"))
    parts = raw_args.strip().split()
    subcommand = parts[0] if parts else "status"
    sub_args = " ".join(parts[1:]) if len(parts) > 1 else ""

    cmd_map: Dict[str, Any] = {
        "status": plugin.cmd_status,
        "reset": plugin.cmd_reset,
        "set_name": plugin.cmd_set_name,
        "emotion": plugin.cmd_emotion,
        "help": plugin.cmd_help,
    }

    handler = cmd_map.get(subcommand)
    if handler:
        return handler(sub_args, **kwargs)

    return f"未知子命令: {subcommand}。使用 /shuxin help 查看帮助。"
