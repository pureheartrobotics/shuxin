from __future__ import annotations

from pathlib import Path
from typing import Any


class VoiceAdapterRegistry:
    """后台预留的受控适配器入口。

    这里只做 allowlist 和参数收敛，真实能力仍在 cli/core/plugins/skills/tools
    各自模块中演进；voice 不修改那些目录。
    """

    def __init__(self, *, shuxin_home: Path) -> None:
        self.shuxin_home = shuxin_home
        self._actions = {
            "skills": {"list": self._skills_list, "read": self._skills_read},
            "tools": {"list": self._tools_list},
            "plugins": {"list": self._plugins_list},
            "agent": {"chat": self._agent_chat_reserved},
            "cli": {"command": self._cli_command_reserved},
        }

    def list_adapters(self) -> list[dict[str, Any]]:
        return [
            {"name": name, "actions": sorted(actions)}
            for name, actions in sorted(self._actions.items())
        ]

    def call(self, adapter_name: str, action: str, params: dict[str, Any]) -> Any:
        adapter = self._actions.get(adapter_name)
        if not adapter or action not in adapter:
            raise PermissionError(f"adapter action is not allowed: {adapter_name}.{action}")
        return adapter[action](params or {})

    def _skills_list(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        from shuxin.skills import SkillManager

        manager = SkillManager()
        manager.initialize()
        category = _optional_str(params.get("category"))
        return [
            {
                "name": skill.name,
                "description": skill.description,
                "category": skill.category,
                "platforms": list(skill.platforms),
                "path": skill.path,
            }
            for skill in manager.list_skills(category=category)
        ]

    def _skills_read(self, params: dict[str, Any]) -> dict[str, Any]:
        from shuxin.skills import SkillManager

        name = _required_str(params, "name")
        manager = SkillManager()
        manager.initialize()
        skill = manager.get_skill(name)
        if skill is None:
            raise ValueError(f"unknown skill: {name}")
        return {
            "name": skill.name,
            "description": skill.description,
            "category": skill.category,
            "platforms": list(skill.platforms),
            "content": skill.content,
            "path": skill.path,
        }

    def _tools_list(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        from shuxin.tools import registry

        category = _optional_str(params.get("category"))
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "category": tool.category,
                "parameters": tool.parameters,
            }
            for tool in registry.list(category=category)
        ]

    def _plugins_list(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        from shuxin.core.plugin import PluginManager

        enabled = params.get("enabled_plugins")
        if enabled is not None and not isinstance(enabled, list):
            raise ValueError("enabled_plugins must be a list when provided")
        manager = PluginManager()
        manager.initialize(shuxin_home=str(self.shuxin_home))
        manager.discover_and_load(enabled_plugins=enabled)
        return manager.list_plugins()

    def _agent_chat_reserved(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(
            "agent.chat adapter is reserved; use the voice WebSocket session until a "
            "bounded admin-side invocation policy is defined"
        )

    def _cli_command_reserved(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(
            "cli.command adapter is reserved and will not execute shell commands from admin API"
        )


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("value must be a string")
    return value


def _required_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} is required")
    return value
