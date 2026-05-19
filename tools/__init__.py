"""舒心工具系统

提供可扩展的工具注册和调用机制，对标 Hermes 的 tools/ 系统。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("shuxin.tools")


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    handler: Callable
    parameters: Dict = field(default_factory=dict)
    category: str = "general"


class ToolRegistry:
    """工具注册表"""

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """注册工具"""
        self._tools[tool.name] = tool
        logger.debug(f"工具已注册: {tool.name}")

    def unregister(self, name: str) -> None:
        """注销工具"""
        self._tools.pop(name, None)

    def get(self, name: str) -> Optional[ToolDefinition]:
        """获取工具"""
        return self._tools.get(name)

    def list(self, category: Optional[str] = None) -> List[ToolDefinition]:
        """列出工具"""
        if category:
            return [t for t in self._tools.values() if t.category == category]
        return list(self._tools.values())

    def call(self, name: str, **kwargs) -> Any:
        """调用工具"""
        tool = self.get(name)
        if not tool:
            raise ValueError(f"未知工具: {name}")
        try:
            return tool.handler(**kwargs)
        except Exception as e:
            logger.error(f"工具调用失败 [{name}]: {e}")
            raise

    def to_openai_tools(self) -> List[Dict]:
        """转换为 OpenAI 工具格式"""
        tools = []
        for tool in self._tools.values():
            openai_tool = {
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
    parameters: Optional[Dict] = None,
    category: str = "general",
):
    """工具注册装饰器"""
    def decorator(func):
        registry.register(ToolDefinition(
            name=name,
            description=description,
            handler=func,
            parameters=parameters or {},
            category=category,
        ))
        return func
    return decorator
