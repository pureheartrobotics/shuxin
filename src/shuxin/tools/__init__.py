"""初心工具系统

提供可扩展的工具注册和调用机制，对标 Hermes 的 tools/ 系统。
支持工具注册、注销、查找、调用，以及转换为 OpenAI 工具格式。

使用方式：
    # 装饰器注册
    @register_tool(name="get_time", description="获取当前时间")
    def get_time() -> str:
        return datetime.now().isoformat()

    # 手动注册
    registry.register(ToolDefinition(
        name="search",
        description="搜索信息",
        handler=search_func,
        parameters={"query": {"type": "string", "description": "搜索关键词"}},
    ))
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("shuxin.tools")


@dataclass
class ToolDefinition:
    """工具定义。

    Attributes:
        name: 工具名称，用于唯一标识。
        description: 工具描述，供 LLM 理解工具用途。
        handler: 工具处理函数。
        parameters: 工具参数定义字典，格式为 {参数名: {type, description, required}}。
        category: 工具分类标签。
    """
    name: str
    description: str
    handler: Callable[..., Any]
    parameters: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    category: str = "general"


class ToolRegistry:
    """工具注册表 — 管理工具的注册、查找和调用。

    线程安全的工具容器，支持按分类筛选和 OpenAI 格式转换。

    Attributes:
        _tools: 工具名称到定义的映射字典。
    """

    def __init__(self) -> None:
        """初始化工具注册表。"""
        self._tools: Dict[str, ToolDefinition] = {}
        self._lock = threading.Lock()

    def register(self, tool: ToolDefinition) -> None:
        """注册工具。

        Args:
            tool: 要注册的工具定义。

        Raises:
            ValueError: 如果工具名称已存在。

        Example:
            >>> registry.register(ToolDefinition(
            ...     name="greet",
            ...     description="打招呼",
            ...     handler=lambda name: f"你好，{name}",
            ... ))
        """
        with self._lock:
            if tool.name in self._tools:
                logger.warning("工具已存在，将被覆盖: %s", tool.name)
            self._tools[tool.name] = tool
            logger.debug("工具已注册: %s [%s]", tool.name, tool.category)

    def unregister(self, name: str) -> None:
        """注销工具。

        Args:
            name: 要注销的工具名称。
        """
        with self._lock:
            self._tools.pop(name, None)
            logger.debug("工具已注销: %s", name)

    def get(self, name: str) -> Optional[ToolDefinition]:
        """获取工具定义。

        Args:
            name: 工具名称。

        Returns:
            Optional[ToolDefinition]: 工具定义，如果不存在返回 None。
        """
        return self._tools.get(name)

    def list(self, category: Optional[str] = None) -> List[ToolDefinition]:
        """列出工具，可按分类筛选。

        Args:
            category: 可选的分类筛选条件。

        Returns:
            List[ToolDefinition]: 匹配的工具定义列表。
        """
        with self._lock:
            if category:
                return [t for t in self._tools.values() if t.category == category]
            return list(self._tools.values())

    def call(self, name: str, **kwargs: Any) -> Any:
        """调用工具。

        Args:
            name: 工具名称。
            **kwargs: 工具参数。

        Returns:
            Any: 工具执行结果。

        Raises:
            ValueError: 如果工具不存在。
            Exception: 工具执行时抛出的异常。
        """
        tool = self.get(name)
        if not tool:
            raise ValueError(f"未知工具: {name}")

        try:
            logger.debug("调用工具: %s (args=%s)", name, kwargs)
            return tool.handler(**kwargs)
        except Exception as e:
            logger.error("工具调用失败 [%s]: %s", name, e)
            raise

    def to_openai_tools(self) -> List[Dict[str, Any]]:
        """转换为 OpenAI 工具调用格式。

        Returns:
            List[Dict[str, Any]]: OpenAI 兼容的工具定义列表。

        Example:
            >>> registry.to_openai_tools()
            [{'type': 'function', 'function': {'name': 'greet', ...}}]
        """
        tools: List[Dict[str, Any]] = []
        with self._lock:
            for tool in self._tools.values():
                openai_tool: Dict[str, Any] = {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": [],
                        },
                    },
                }
                # 添加参数
                for param_name, param_info in tool.parameters.items():
                    openai_tool["function"]["parameters"]["properties"][param_name] = {
                        "type": param_info.get("type", "string"),
                        "description": param_info.get("description", ""),
                    }
                    if param_info.get("required", False):
                        openai_tool["function"]["parameters"]["required"].append(param_name)

                tools.append(openai_tool)

        return tools


# 全局工具注册表
registry = ToolRegistry()


def register_tool(
    name: str,
    description: str,
    parameters: Optional[Dict[str, Dict[str, Any]]] = None,
    category: str = "general",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """工具注册装饰器。

    用于将函数注册为工具，简化注册流程。

    Args:
        name: 工具名称。
        description: 工具描述。
        parameters: 可选的参数定义。
        category: 工具分类。

    Returns:
        Callable: 装饰器函数。

    Example:
        >>> @register_tool(name="say_hello", description="打招呼")
        ... def say_hello(name: str) -> str:
        ...     return f"你好，{name}"
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        registry.register(ToolDefinition(
            name=name,
            description=description,
            handler=func,
            parameters=parameters or {},
            category=category,
        ))
        return func
    return decorator
