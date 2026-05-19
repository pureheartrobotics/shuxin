"""舒心插件系统

对标 Hermes 的 PluginManager，支持从多个来源发现和加载插件。
插件通过 register(ctx) 函数注册 hooks、命令和工具。
"""

from __future__ import annotations

import os
import sys
import yaml
import logging
import importlib
import inspect
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Union
from dataclasses import dataclass, field

logger = logging.getLogger("shuxin.plugin")


# 有效 Hook 名称
VALID_HOOKS: Set[str] = {
    "pre_llm_call",        # LLM 调用前
    "post_llm_call",       # LLM 调用后
    "transform_output",    # 输出转换
    "pre_tool_call",       # 工具调用前
    "post_tool_call",      # 工具调用后
    "on_session_start",    # 会话开始
    "on_session_end",      # 会话结束
    "on_user_message",     # 用户消息
    "on_ai_message",       # AI 消息
}


@dataclass
class PluginManifest:
    """插件清单"""
    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    kind: str = "standalone"  # standalone, memory, context_engine
    hooks: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)


@dataclass
class LoadedPlugin:
    """已加载的插件实例"""
    manifest: PluginManifest
    module: Any = None
    commands: Dict[str, Callable] = field(default_factory=dict)
    hooks: Dict[str, List[Callable]] = field(default_factory=dict)
    tools: List[Dict] = field(default_factory=list)


class PluginContext:
    """插件上下文 — 插件与框架交互的门面"""

    def __init__(self, manifest: PluginManifest, manager: "PluginManager"):
        self.manifest = manifest
        self._manager = manager
        self._loaded_plugin: Optional[LoadedPlugin] = None

    def register_hook(self, hook_name: str, callback: Callable) -> None:
        """注册 Hook"""
        if hook_name not in VALID_HOOKS:
            logger.warning(f"未知的 hook 名称: {hook_name}，跳过")
            return
        if self._loaded_plugin is None:
            logger.warning("插件未加载，无法注册 hook")
            return
        if hook_name not in self._loaded_plugin.hooks:
            self._loaded_plugin.hooks[hook_name] = []
        self._loaded_plugin.hooks[hook_name].append(callback)
        logger.debug(f"插件 [{self.manifest.name}] 注册了 hook: {hook_name}")

    def register_command(self, name: str, handler: Callable) -> None:
        """注册斜杠命令"""
        if self._loaded_plugin is None:
            logger.warning("插件未加载，无法注册命令")
            return
        self._loaded_plugin.commands[name] = handler
        logger.debug(f"插件 [{self.manifest.name}] 注册了命令: /{name}")

    def register_tool(self, tool_def: Dict) -> None:
        """注册工具"""
        if self._loaded_plugin is None:
            logger.warning("插件未加载，无法注册工具")
            return
        self._loaded_plugin.tools.append(tool_def)
        logger.debug(f"插件 [{self.manifest.name}] 注册了工具: {tool_def.get('name', 'unknown')}")

    @property
    def llm(self) -> Any:
        """获取 LLM 提供者（懒加载）"""
        return self._manager.llm_provider


class PluginManager:
    """插件管理器 — 发现、加载、调用插件"""

    def __init__(self):
        self._plugins: Dict[str, LoadedPlugin] = {}
        self._plugin_dirs: List[Path] = []
        self._initialized = False
        self.llm_provider = None

    def initialize(self, shuxin_home: Optional[str] = None) -> None:
        """初始化插件系统"""
        if self._initialized:
            return

        shuxin_home_path = Path(shuxin_home) if shuxin_home else Path.home() / ".shuxin"

        # 插件搜索路径
        self._plugin_dirs = [
            # 1. 内置插件
            Path(__file__).parent.parent / "plugins",
            # 2. 用户插件
            shuxin_home_path / "plugins",
            # 3. 项目插件
            Path.cwd() / ".shuxin" / "plugins",
        ]

        self._initialized = True
        logger.info("插件系统已初始化")

    def discover_and_load(self, enabled_plugins: Optional[List[str]] = None) -> None:
        """发现并加载插件"""
        if not self._initialized:
            self.initialize()

        discovered = []

        # 扫描所有插件目录
        for plugin_dir in self._plugin_dirs:
            if plugin_dir.exists():
                for item in plugin_dir.iterdir():
                    if item.is_dir() and (item / "__init__.py").exists():
                        manifest_file = item / "plugin.yaml"
                        if manifest_file.exists():
                            manifest = self._parse_manifest(manifest_file)
                            if manifest:
                                discovered.append((manifest, item))

        # 过滤启用的插件
        if enabled_plugins:
            discovered = [
                (m, p) for m, p in discovered
                if m.name in enabled_plugins
            ]

        # 加载插件
        for manifest, plugin_path in discovered:
            self._load_plugin(manifest, plugin_path)

        logger.info(f"已加载 {len(self._plugins)} 个插件: {list(self._plugins.keys())}")

    def _parse_manifest(self, manifest_path: Path) -> Optional[PluginManifest]:
        """解析 plugin.yaml"""
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            return PluginManifest(
                name=data.get("name", manifest_path.parent.name),
                version=data.get("version", "1.0.0"),
                description=data.get("description", ""),
                author=data.get("author", ""),
                kind=data.get("kind", "standalone"),
                hooks=data.get("hooks", []),
                dependencies=data.get("dependencies", []),
            )
        except Exception as e:
            logger.warning(f"解析插件清单失败 {manifest_path}: {e}")
            return None

    def _load_plugin(self, manifest: PluginManifest, plugin_path: Path) -> None:
        """加载单个插件"""
        try:
            # 动态导入插件模块
            spec = importlib.util.spec_from_file_location(
                f"shuxin_plugin_{manifest.name}",
                plugin_path / "__init__.py",
            )
            if spec is None or spec.loader is None:
                logger.warning(f"无法加载插件模块: {manifest.name}")
                return

            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)

            # 创建插件实例
            loaded = LoadedPlugin(manifest=manifest, module=module)

            # 创建上下文并调用 register
            ctx = PluginContext(manifest, self)
            ctx._loaded_plugin = loaded

            if hasattr(module, "register"):
                module.register(ctx)
                self._plugins[manifest.name] = loaded
                logger.info(f"插件已加载: {manifest.name} v{manifest.version}")
            else:
                logger.warning(f"插件缺少 register() 函数: {manifest.name}")

        except Exception as e:
            logger.error(f"加载插件失败 [{manifest.name}]: {e}", exc_info=True)

    def invoke_hook(self, hook_name: str, **kwargs) -> List[Any]:
        """调用指定 Hook 的所有注册回调"""
        if hook_name not in VALID_HOOKS:
            logger.warning(f"调用未知 hook: {hook_name}")
            return []

        results = []
        for plugin_name, plugin in self._plugins.items():
            callbacks = plugin.hooks.get(hook_name, [])
            for callback in callbacks:
                try:
                    result = callback(**kwargs)
                    results.append((plugin_name, result))
                except Exception as e:
                    logger.error(f"插件 [{plugin_name}] hook [{hook_name}] 执行失败: {e}")

        return results

    def get_command_handler(self, name: str) -> Optional[Callable]:
        """获取命令处理器"""
        for plugin in self._plugins.values():
            if name in plugin.commands:
                return plugin.commands[name]
        return None

    def get_all_commands(self) -> Dict[str, str]:
        """获取所有注册的命令"""
        commands = {}
        for plugin in self._plugins.values():
            for cmd_name in plugin.commands:
                commands[cmd_name] = plugin.manifest.description
        return commands

    def get_plugin(self, name: str) -> Optional[LoadedPlugin]:
        """获取已加载的插件"""
        return self._plugins.get(name)

    def list_plugins(self) -> List[Dict]:
        """列出所有已加载的插件"""
        return [
            {
                "name": p.manifest.name,
                "version": p.manifest.version,
                "description": p.manifest.description,
                "kind": p.manifest.kind,
                "hooks": list(p.hooks.keys()),
                "commands": list(p.commands.keys()),
            }
            for p in self._plugins.values()
        ]
