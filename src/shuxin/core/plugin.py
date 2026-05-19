"""
舒心插件系统
============

发现、加载、管理插件的完整生命周期。受 Hermes Agent 插件架构启发，
但为陪伴型 AI 场景做了针对性设计。

插件来源（按优先级升序）:
1. **内置插件** — ``<shuxin>/plugins/<name>/``（随框架发行）
2. **用户插件** — ``~/.shuxin/plugins/<name>/``（用户自安装）
3. **项目插件** — ``./.shuxin/plugins/<name>/``（项目级覆盖）

每个目录插件必须包含 ``plugin.yaml`` 清单 **和** ``__init__.py``
且暴露 ``register(ctx)`` 函数。

生命周期 Hook
-------------
插件可注册以下任意 Hook 的回调，框架在适当时机调用 ``invoke_hook()``:

- ``pre_llm_call``      — LLM 调用前注入上下文
- ``post_llm_call``     — LLM 调用后处理结果
- ``transform_output``  — 输出转换/拦截
- ``pre_tool_call``     — 工具调用前校验
- ``post_tool_call``    — 工具调用后处理
- ``on_session_start``  — 会话开始
- ``on_session_end``    — 会话结束
- ``on_user_message``   — 用户消息到达
- ``on_ai_message``     — AI 回复生成
"""

from __future__ import annotations

import os
import sys
import yaml
import logging
import importlib
import importlib.util
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Union
from dataclasses import dataclass, field

logger = logging.getLogger("shuxin.plugin")

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

VALID_HOOKS: Set[str] = {
    "pre_llm_call",
    "post_llm_call",
    "transform_output",
    "pre_tool_call",
    "post_tool_call",
    "on_session_start",
    "on_session_end",
    "on_user_message",
    "on_ai_message",
}

# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------


@dataclass
class PluginManifest:
    """插件清单 — 从 ``plugin.yaml`` 解析而来。

    Attributes:
        name: 插件唯一标识名。
        version: 语义化版本号。
        description: 简短描述，显示在 ``/help`` 中。
        author: 作者信息。
        kind: 插件类型（``standalone`` / ``memory`` / ``context_engine``）。
        hooks: 声明的 Hook 列表（用于快速校验）。
        dependencies: Python 包依赖列表。
    """

    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    kind: str = "standalone"
    hooks: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)


@dataclass
class LoadedPlugin:
    """已加载的插件实例 — 框架内部使用。

    Attributes:
        manifest: 对应的插件清单。
        module: 导入的 Python 模块对象。
        commands: 注册的斜杠命令 {名称: 处理器}。
        hooks: 注册的 Hook 回调 {hook名: [回调列表]}。
        tools: 注册的工具定义列表。
    """

    manifest: PluginManifest
    module: Any = None
    commands: Dict[str, Callable] = field(default_factory=dict)
    hooks: Dict[str, List[Callable]] = field(default_factory=dict)
    tools: List[Dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 插件上下文
# ---------------------------------------------------------------------------


class PluginContext:
    """插件上下文门面 — 插件与框架交互的唯一入口。

    插件通过 ``register(ctx)`` 接收此对象，调用其方法注册
    Hook、命令和工具。框架保证此对象线程安全。
    """

    def __init__(self, manifest: PluginManifest, manager: "PluginManager") -> None:
        self.manifest = manifest
        self._manager = manager
        self._loaded_plugin: Optional[LoadedPlugin] = None
        self._lock = threading.Lock()

    # -- Hook 注册 ----------------------------------------------------------

    def register_hook(self, hook_name: str, callback: Callable) -> None:
        """注册一个生命周期 Hook。

        Args:
            hook_name: Hook 名称，必须是 ``VALID_HOOKS`` 中的一员。
            callback: 回调函数，接收 ``**kwargs``。

        Raises:
            ValueError: 如果 ``hook_name`` 不在 ``VALID_HOOKS`` 中。
            RuntimeError: 如果插件尚未加载完成。
        """
        if hook_name not in VALID_HOOKS:
            raise ValueError(
                f"未知的 hook 名称: {hook_name!r}。"
                f"有效值: {', '.join(sorted(VALID_HOOKS))}"
            )
        if self._loaded_plugin is None:
            raise RuntimeError(f"插件 [{self.manifest.name}] 尚未加载完成，无法注册 hook")

        with self._lock:
            if hook_name not in self._loaded_plugin.hooks:
                self._loaded_plugin.hooks[hook_name] = []
            self._loaded_plugin.hooks[hook_name].append(callback)

        logger.debug("插件 [%s] 注册了 hook: %s", self.manifest.name, hook_name)

    # -- 命令注册 ----------------------------------------------------------

    def register_command(self, name: str, handler: Callable) -> None:
        """注册一个斜杠命令（如 ``/shuxin``）。

        Args:
            name: 命令名称（不含前导斜杠）。
            handler: 处理函数，签名 ``handler(raw_args: str, **kwargs) -> str``。

        Raises:
            RuntimeError: 如果插件尚未加载完成。
        """
        if self._loaded_plugin is None:
            raise RuntimeError(f"插件 [{self.manifest.name}] 尚未加载完成，无法注册命令")

        with self._lock:
            self._loaded_plugin.commands[name] = handler

        logger.debug("插件 [%s] 注册了命令: /%s", self.manifest.name, name)

    # -- 工具注册 ----------------------------------------------------------

    def register_tool(self, tool_def: Dict) -> None:
        """注册一个可调用工具。

        Args:
            tool_def: 工具定义字典，至少包含 ``name`` 和 ``handler`` 键。

        Raises:
            RuntimeError: 如果插件尚未加载完成。
            ValueError: 如果 ``tool_def`` 缺少必要字段。
        """
        if self._loaded_plugin is None:
            raise RuntimeError(f"插件 [{self.manifest.name}] 尚未加载完成，无法注册工具")

        if "name" not in tool_def or "handler" not in tool_def:
            raise ValueError("工具定义必须包含 'name' 和 'handler' 字段")

        with self._lock:
            self._loaded_plugin.tools.append(tool_def)

        logger.debug("插件 [%s] 注册了工具: %s", self.manifest.name, tool_def.get("name", "?"))

    # -- LLM 访问 ----------------------------------------------------------

    @property
    def llm(self) -> Any:
        """获取框架的 LLM 提供者（懒加载）。

        Returns:
            LLM 提供者实例，或 ``None``（如果尚未初始化）。
        """
        return self._manager.llm_provider


# ---------------------------------------------------------------------------
# 插件管理器
# ---------------------------------------------------------------------------


class PluginManager:
    """插件管理器 — 发现、加载、调用插件的核心类。

    用法::

        mgr = PluginManager()
        mgr.initialize(shuxin_home="/path/to/.shuxin")
        mgr.discover_and_load(enabled_plugins=["companion"])
        mgr.invoke_hook("on_session_start", agent=agent)
    """

    def __init__(self) -> None:
        self._plugins: Dict[str, LoadedPlugin] = {}
        self._plugin_dirs: List[Path] = []
        self._lock = threading.Lock()
        self._initialized = False

        # 外部注入
        self.llm_provider: Any = None

    # -- 初始化 ------------------------------------------------------------

    def initialize(self, shuxin_home: Optional[str] = None) -> None:
        """初始化插件系统，设定搜索路径。

        Args:
            shuxin_home: 舒心家目录路径。为 ``None`` 时使用 ``~/.shuxin``。
        """
        if self._initialized:
            logger.debug("插件系统已初始化，跳过重复初始化")
            return

        shuxin_home_path = Path(shuxin_home) if shuxin_home else Path.home() / ".shuxin"

        self._plugin_dirs = [
            # 1. 内置插件 — 随框架发行
            Path(__file__).resolve().parent.parent / "plugins",
            # 2. 用户插件 — 用户自安装
            shuxin_home_path / "plugins",
            # 3. 项目插件 — 项目级覆盖
            Path.cwd() / ".shuxin" / "plugins",
        ]

        self._initialized = True
        logger.info("插件系统已初始化，搜索路径: %s", [str(d) for d in self._plugin_dirs])

    # -- 发现与加载 --------------------------------------------------------

    def discover_and_load(
        self, enabled_plugins: Optional[List[str]] = None
    ) -> None:
        """发现所有可用插件并加载启用的插件。

        Args:
            enabled_plugins: 允许加载的插件名称列表。
                ``None`` 表示加载所有发现的插件。
        """
        if not self._initialized:
            self.initialize()

        discovered: List[tuple[PluginManifest, Path]] = []

        # 扫描所有插件目录
        for plugin_dir in self._plugin_dirs:
            if not plugin_dir.exists():
                logger.debug("插件目录不存在，跳过: %s", plugin_dir)
                continue

            for item in sorted(plugin_dir.iterdir()):
                if not item.is_dir():
                    continue
                init_file = item / "__init__.py"
                manifest_file = item / "plugin.yaml"
                if not init_file.exists() or not manifest_file.exists():
                    continue

                manifest = self._parse_manifest(manifest_file)
                if manifest is not None:
                    discovered.append((manifest, item))

        # 过滤启用的插件
        if enabled_plugins is not None:
            enabled_set = set(enabled_plugins)
            discovered = [
                (m, p) for m, p in discovered if m.name in enabled_set
            ]
            skipped = [m.name for m, _ in discovered if m.name not in enabled_set]
            if skipped:
                logger.debug("以下插件被禁用: %s", skipped)

        # 加载插件
        loaded_count = 0
        for manifest, plugin_path in discovered:
            if self._load_plugin(manifest, plugin_path):
                loaded_count += 1

        logger.info(
            "插件加载完成: %d/%d 成功",
            loaded_count,
            len(discovered),
        )

    def _parse_manifest(self, manifest_path: Path) -> Optional[PluginManifest]:
        """解析 ``plugin.yaml`` 文件为 ``PluginManifest``。

        Args:
            manifest_path: ``plugin.yaml`` 的完整路径。

        Returns:
            解析成功的 ``PluginManifest``，失败返回 ``None``。
        """
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not isinstance(data, dict):
                logger.warning("插件清单格式无效（非字典）: %s", manifest_path)
                return None

            return PluginManifest(
                name=data.get("name", manifest_path.parent.name),
                version=data.get("version", "1.0.0"),
                description=data.get("description", ""),
                author=data.get("author", ""),
                kind=data.get("kind", "standalone"),
                hooks=data.get("hooks", []),
                dependencies=data.get("dependencies", []),
            )
        except FileNotFoundError:
            logger.warning("插件清单文件不存在: %s", manifest_path)
            return None
        except yaml.YAMLError as e:
            logger.warning("插件清单 YAML 解析失败 %s: %s", manifest_path, e)
            return None
        except Exception as e:
            logger.warning("解析插件清单异常 %s: %s", manifest_path, e)
            return None

    def _load_plugin(
        self, manifest: PluginManifest, plugin_path: Path
    ) -> bool:
        """加载单个插件模块并调用其 ``register()``。

        Args:
            manifest: 插件清单。
            plugin_path: 插件目录路径。

        Returns:
            加载成功返回 ``True``，否则 ``False``。
        """
        try:
            # 动态导入插件模块
            module_name = f"_shuxin_plugin_{manifest.name}"
            spec = importlib.util.spec_from_file_location(
                module_name,
                plugin_path / "__init__.py",
            )
            if spec is None or spec.loader is None:
                logger.warning("无法创建插件模块规格: %s", manifest.name)
                return False

            module = importlib.util.module_from_spec(spec)

            # 检查 register 函数是否存在
            if not hasattr(module, "register"):
                logger.warning(
                    "插件 [%s] 缺少 register(ctx) 函数，跳过加载",
                    manifest.name,
                )
                return False

            # 注册模块到 sys.modules 防止重复导入
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # 创建插件实例
            loaded = LoadedPlugin(manifest=manifest, module=module)

            # 创建上下文并调用 register
            ctx = PluginContext(manifest, self)
            ctx._loaded_plugin = loaded

            try:
                module.register(ctx)
            except Exception as e:
                logger.error(
                    "插件 [%s] register() 执行失败: %s",
                    manifest.name,
                    e,
                    exc_info=True,
                )
                return False

            with self._lock:
                self._plugins[manifest.name] = loaded

            logger.info(
                "插件已加载: %s v%s (%s)",
                manifest.name,
                manifest.version,
                manifest.kind,
            )
            return True

        except ImportError as e:
            logger.error(
                "插件 [%s] 导入失败（缺少依赖?）: %s",
                manifest.name,
                e,
            )
            return False
        except Exception as e:
            logger.error(
                "加载插件 [%s] 时发生未预期异常: %s",
                manifest.name,
                e,
                exc_info=True,
            )
            return False

    # -- Hook 调用 ---------------------------------------------------------

    def invoke_hook(
        self, hook_name: str, **kwargs: Any
    ) -> List[tuple[str, Any]]:
        """调用指定 Hook 的所有已注册回调。

        每个回调独立执行，一个失败不影响其他回调。
        这是**同步**调用；异步 Hook 暂不支持。

        Args:
            hook_name: Hook 名称。
            **kwargs: 传递给回调的上下文参数。

        Returns:
            ``[(plugin_name, result), ...]`` 列表。
            失败的回调返回 ``(plugin_name, None)``。

        Raises:
            ValueError: 如果 ``hook_name`` 不在 ``VALID_HOOKS`` 中。
        """
        if hook_name not in VALID_HOOKS:
            raise ValueError(
                f"未知的 hook 名称: {hook_name!r}。"
                f"有效值: {', '.join(sorted(VALID_HOOKS))}"
            )

        results: List[tuple[str, Any]] = []

        with self._lock:
            # 在锁内获取回调快照，避免迭代时被修改
            snapshots: List[tuple[str, Callable]] = []
            for plugin_name, plugin in self._plugins.items():
                callbacks = list(plugin.hooks.get(hook_name, []))
                for cb in callbacks:
                    snapshots.append((plugin_name, cb))

        # 在锁外执行回调
        for plugin_name, callback in snapshots:
            try:
                result = callback(**kwargs)
                results.append((plugin_name, result))
                logger.debug(
                    "Hook [%s] 插件 [%s] 执行成功",
                    hook_name,
                    plugin_name,
                )
            except Exception as e:
                logger.error(
                    "插件 [%s] Hook [%s] 执行失败: %s",
                    plugin_name,
                    hook_name,
                    e,
                    exc_info=True,
                )
                results.append((plugin_name, None))

        return results

    # -- 命令查询 ---------------------------------------------------------

    def get_command_handler(self, name: str) -> Optional[Callable]:
        """根据命令名称查找处理器。

        Args:
            name: 命令名称（不含前导斜杠）。

        Returns:
            处理器函数，未找到返回 ``None``。
        """
        with self._lock:
            for plugin in self._plugins.values():
                if name in plugin.commands:
                    return plugin.commands[name]
        return None

    def get_all_commands(self) -> Dict[str, str]:
        """获取所有已注册的命令。

        Returns:
            ``{命令名: 插件描述}`` 字典。
        """
        commands: Dict[str, str] = {}
        with self._lock:
            for plugin in self._plugins.values():
                for cmd_name in plugin.commands:
                    commands[cmd_name] = plugin.manifest.description
        return commands

    # -- 插件查询 ---------------------------------------------------------

    def get_plugin(self, name: str) -> Optional[LoadedPlugin]:
        """按名称获取已加载的插件。

        Args:
            name: 插件名称。

        Returns:
            ``LoadedPlugin`` 实例，未找到返回 ``None``。
        """
        with self._lock:
            return self._plugins.get(name)

    def list_plugins(self) -> List[Dict[str, Any]]:
        """列出所有已加载的插件信息。

        Returns:
            插件信息字典列表，每个包含 name/version/description/kind/hooks/commands。
        """
        with self._lock:
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
