"""把陪伴插件接到 Hermes 生命周期 hooks（不含自尊）。"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any, Optional

logger = logging.getLogger("shuxin.hermes.companion")

_HOOKS_INSTALLED = False
_CURRENT_AGENT: ContextVar[Any] = ContextVar("shuxin_hermes_voice_agent", default=None)


def bind_voice_agent(agent: Any) -> Any:
    return _CURRENT_AGENT.set(agent)


def reset_voice_agent(token: Any) -> None:
    _CURRENT_AGENT.reset(token)


def current_voice_agent() -> Any:
    return _CURRENT_AGENT.get()


def _plugin_for(agent: Any):
    from shuxin.plugins.companion import get_plugin_for_agent

    return get_plugin_for_agent(agent)


def _on_pre_llm_call(**kwargs: Any) -> Any:
    agent = _CURRENT_AGENT.get()
    message = str(kwargs.get("user_message") or "")
    plugin = _plugin_for(agent)
    plugin.on_user_message(message=message, agent=agent)
    block = plugin.on_pre_llm_call(agent=agent)
    if block and str(block).strip():
        return {"context": str(block).strip()}
    return None


def _on_transform_llm_output(**kwargs: Any) -> Any:
    agent = _CURRENT_AGENT.get()
    content = kwargs.get("response_text") or kwargs.get("content") or ""
    plugin = _plugin_for(agent)
    return plugin.on_transform_output(content=content, agent=agent)


def _on_session_start(**kwargs: Any) -> None:
    _plugin_for(_CURRENT_AGENT.get()).on_session_start(**kwargs)


def _on_session_end(**kwargs: Any) -> None:
    _plugin_for(_CURRENT_AGENT.get()).on_session_end(**kwargs)


def install_companion_hooks() -> None:
    """向 Hermes PluginManager 注册陪伴 hooks（幂等）。"""
    global _HOOKS_INSTALLED
    if _HOOKS_INSTALLED:
        return
    try:
        from hermes_cli.plugins import PluginContext, PluginManifest, get_plugin_manager
    except Exception as exc:
        logger.warning("skip companion Hermes hooks: %s", exc)
        return
    manager = get_plugin_manager()
    try:
        manager.discover_and_load()
    except Exception:
        logger.debug("Hermes plugin discover failed", exc_info=True)
    manifest = PluginManifest(
        name="companion",
        version="1.0.0",
        description="舒心陪伴（情感、守护、用户画像；自尊默认关闭）",
        source="user",
        kind="standalone",
        key="companion",
        provides_hooks=["pre_llm_call", "transform_llm_output", "on_session_start", "on_session_end"],
    )
    ctx = PluginContext(manifest, manager)
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
    ctx.register_hook("transform_llm_output", _on_transform_llm_output)
    ctx.register_hook("on_session_start", _on_session_start)
    ctx.register_hook("on_session_end", _on_session_end)
    _HOOKS_INSTALLED = True
    logger.info("Hermes companion hooks installed (self-esteem off by default)")
