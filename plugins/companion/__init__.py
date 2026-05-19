"""舒心陪伴插件 — 插件入口

注册到舒心框架的插件系统，通过 hooks 和命令与核心交互。
"""

from __future__ import annotations

import logging
from typing import Optional, Dict, Any

from shuxin.plugins.companion.self_esteem import SelfEsteemSystem
from shuxin.plugins.companion.emotion import EmotionEngine
from shuxin.plugins.companion.guardian import GuardianSystem
from shuxin.plugins.companion.user_model import UserModel
from shuxin.plugins.companion.interceptor import ResponseInterceptor

logger = logging.getLogger("shuxin.plugins.companion")


class CompanionPlugin:
    """陪伴插件主类 — 协调所有子系统"""

    def __init__(self):
        self.self_esteem = SelfEsteemSystem()
        self.emotion = EmotionEngine()
        self.guardian = GuardianSystem()
        self.user_model = UserModel()
        self.interceptor = ResponseInterceptor()
        self._initialized = False

    def initialize(self) -> None:
        """初始化所有子系统"""
        if self._initialized:
            return
        self._initialized = True
        logger.info("陪伴系统已初始化")

    # ---- Hooks ----

    def on_pre_llm_call(self, **kwargs) -> Optional[str]:
        """pre_llm_call hook — 注入情感和用户上下文"""
        if not self._initialized:
            self.initialize()

        # 注入情感状态
        emotion_context = self.emotion.get_emotion_context()

        # 注入用户画像
        profile_context = self.user_model.get_profile_context()

        # 注入自尊状态
        esteem_status = self.self_esteem.get_status_text()

        return (
            f"## 舒心当前状态\n\n"
            f"{esteem_status}\n\n"
            f"{emotion_context}\n\n"
            f"{profile_context}"
        )

    def on_transform_output(self, **kwargs) -> Optional[str]:
        """transform_output hook — 沉默模式拦截"""
        if not self._initialized:
            self.initialize()

        content = kwargs.get("content", "")
        agent = kwargs.get("agent")

        if self.self_esteem.state.is_silent:
            # 确定沉默阶段
            import time
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

    def on_session_start(self, **kwargs) -> None:
        """on_session_start hook — 会话开始"""
        if not self._initialized:
            self.initialize()
        logger.info("陪伴系统会话开始")

    def on_session_end(self, **kwargs) -> None:
        """on_session_end hook — 会话结束"""
        logger.info("陪伴系统会话结束")

    def on_user_message(self, **kwargs) -> None:
        """on_user_message hook — 处理用户消息"""
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

        # 5. 守护系统评估
        guardian_result = self.guardian.evaluate(message)
        if guardian_result and agent:
            # 如果触发了守护场景，注入到对话上下文
            logger.info(f"守护触发: {guardian_result['name']}")

    def on_ai_message(self, **kwargs) -> None:
        """on_ai_message hook — AI 消息处理"""
        pass

    # ---- 命令 ----

    def cmd_status(self, args: str, **kwargs) -> str:
        """查看舒心完整状态"""
        return (
            f"## 舒心状态总览\n\n"
            f"### 自尊系统\n{self.self_esteem.get_status_text()}\n"
            f"### 情感状态\n{self.emotion.get_status_text()}\n"
            f"### 守护系统\n{self.guardian.get_status_text()}\n"
            f"### 用户关系\n{self.user_model.get_status_text()}"
        )

    def cmd_reset(self, args: str, **kwargs) -> str:
        """重置自尊系统"""
        self.self_esteem.reset()
        return "自尊系统已重置。"

    def cmd_set_name(self, args: str, **kwargs) -> str:
        """设置用户名字"""
        if args.strip():
            self.user_model.update_profile("name", args.strip())
            return f"好的，我记住你了，{args.strip()}。"
        return "请提供名字: /shuxin set_name <你的名字>"

    def cmd_emotion(self, args: str, **kwargs) -> str:
        """查看情感状态"""
        return self.emotion.get_status_text()

    def cmd_help(self, args: str, **kwargs) -> str:
        """帮助信息"""
        return (
            "## 舒心陪伴系统命令\n\n"
            "/shuxin status    — 查看完整状态\n"
            "/shuxin emotion   — 查看情感状态\n"
            "/shuxin reset     — 重置自尊系统\n"
            "/shuxin set_name  — 设置你的名字\n"
            "/shuxin help      — 显示此帮助"
        )


# ---- 插件注册入口 ----

_plugin_instance: Optional[CompanionPlugin] = None


def get_plugin() -> CompanionPlugin:
    """获取插件单例"""
    global _plugin_instance
    if _plugin_instance is None:
        _plugin_instance = CompanionPlugin()
    return _plugin_instance


def register(ctx) -> None:
    """Hermes 兼容的插件注册函数"""
    plugin = get_plugin()

    # 注册 hooks
    ctx.register_hook("pre_llm_call", plugin.on_pre_llm_call)
    ctx.register_hook("transform_output", plugin.on_transform_output)
    ctx.register_hook("on_session_start", plugin.on_session_start)
    ctx.register_hook("on_session_end", plugin.on_session_end)
    ctx.register_hook("on_user_message", plugin.on_user_message)
    ctx.register_hook("on_ai_message", plugin.on_ai_message)

    # 注册命令
    ctx.register_command("shuxin", _handle_shuxin_command)

    logger.info("陪伴插件已注册")


def _handle_shuxin_command(raw_args: str, **kwargs) -> str:
    """处理 /shuxin 命令"""
    plugin = get_plugin()
    parts = raw_args.strip().split()
    subcommand = parts[0] if parts else "status"
    sub_args = " ".join(parts[1:]) if len(parts) > 1 else ""

    cmd_map = {
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
