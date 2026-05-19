"""舒心配置管理模块

支持 YAML 配置文件 + 环境变量覆盖，对标 Hermes 的配置系统。
"""

from __future__ import annotations

import os
import yaml
import logging
from pathlib import Path
from typing import Any, Dict, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("shuxin.config")

# 默认配置路径
SHUXIN_HOME_ENV = "SHUXIN_HOME"
DEFAULT_SHUXIN_HOME = Path.home() / ".shuxin"


def get_shuxin_home() -> Path:
    """获取舒心家目录，优先环境变量"""
    env_home = os.environ.get(SHUXIN_HOME_ENV)
    if env_home:
        return Path(env_home)
    return DEFAULT_SHUXIN_HOME


@dataclass
class LLMConfig:
    """LLM 提供者配置"""
    provider: str = "openai"          # openai, anthropic, custom
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7
    top_p: float = 0.9


@dataclass
class SoulConfig:
    """人格系统配置"""
    soul_path: str = ""               # SOUL.md 路径，空则使用默认
    auto_load: bool = True


@dataclass
class CompanionConfig:
    """陪伴系统配置"""
    enabled: bool = True
    self_esteem_enabled: bool = True
    emotion_enabled: bool = True
    guardian_enabled: bool = True
    user_model_enabled: bool = True
    data_dir: str = ""                # 数据持久化目录


@dataclass
class Config:
    """舒心主配置"""
    # 核心
    debug: bool = False
    verbose: bool = False
    shuxin_home: str = str(get_shuxin_home())

    # 子配置
    llm: LLMConfig = field(default_factory=LLMConfig)
    soul: SoulConfig = field(default_factory=SoulConfig)
    companion: CompanionConfig = field(default_factory=CompanionConfig)

    # 插件
    enabled_plugins: list = field(default_factory=lambda: ["companion"])
    disabled_plugins: list = field(default_factory=list)

    # 会话
    session_timeout: int = 3600       # 会话超时（秒）
    max_history: int = 100            # 最大历史消息数

    @classmethod
    def load(cls, path: Optional[str] = None) -> "Config":
        """从 YAML 文件加载配置，支持环境变量覆盖"""
        cfg = cls()

        # 1. 尝试加载配置文件
        config_paths = []
        if path:
            config_paths.append(Path(path))
        config_paths.append(get_shuxin_home() / "config.yaml")
        config_paths.append(Path.cwd() / ".shuxin.yaml")
        config_paths.append(Path.cwd() / ".shuxin.yml")

        for cp in config_paths:
            if cp.exists():
                try:
                    with open(cp, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f)
                    if data:
                        cfg._merge_dict(data)
                    logger.info(f"已加载配置文件: {cp}")
                    break
                except Exception as e:
                    logger.warning(f"加载配置文件失败 {cp}: {e}")

        # 2. 环境变量覆盖
        cfg._apply_env_overrides()

        return cfg

    def _merge_dict(self, data: Dict[str, Any]) -> None:
        """递归合并字典到配置"""
        for key, value in data.items():
            if key == "llm" and isinstance(value, dict):
                for k, v in value.items():
                    if hasattr(self.llm, k):
                        setattr(self.llm, k, v)
            elif key == "soul" and isinstance(value, dict):
                for k, v in value.items():
                    if hasattr(self.soul, k):
                        setattr(self.soul, k, v)
            elif key == "companion" and isinstance(value, dict):
                for k, v in value.items():
                    if hasattr(self.companion, k):
                        setattr(self.companion, k, v)
            elif hasattr(self, key):
                setattr(self, key, value)

    def _apply_env_overrides(self) -> None:
        """环境变量覆盖配置"""
        env_map = {
            "SHUXIN_LLM_PROVIDER": ("llm", "provider"),
            "SHUXIN_LLM_MODEL": ("llm", "model"),
            "SHUXIN_API_KEY": ("llm", "api_key"),
            "SHUXIN_BASE_URL": ("llm", "base_url"),
            "SHUXIN_DEBUG": ("debug", None),
            "SHUXIN_VERBOSE": ("verbose", None),
        }
        for env_name, (attr, sub_attr) in env_map.items():
            val = os.environ.get(env_name)
            if val is not None:
                if sub_attr:
                    obj = getattr(self, attr)
                    setattr(obj, sub_attr, val)
                else:
                    # 布尔转换
                    if val.lower() in ("1", "true", "yes"):
                        setattr(self, attr, True)
                    elif val.lower() in ("0", "false", "no"):
                        setattr(self, attr, False)
                    else:
                        setattr(self, attr, val)

    def save(self, path: Optional[str] = None) -> None:
        """保存配置到文件"""
        save_path = path or str(get_shuxin_home() / "config.yaml")
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)

        data = {
            "debug": self.debug,
            "verbose": self.verbose,
            "llm": {
                "provider": self.llm.provider,
                "model": self.llm.model,
                "api_key": self.llm.api_key if self.llm.api_key else "",
                "base_url": self.llm.base_url,
                "max_tokens": self.llm.max_tokens,
                "temperature": self.llm.temperature,
                "top_p": self.llm.top_p,
            },
            "soul": {
                "soul_path": self.soul.soul_path,
                "auto_load": self.soul.auto_load,
            },
            "companion": {
                "enabled": self.companion.enabled,
                "self_esteem_enabled": self.companion.self_esteem_enabled,
                "emotion_enabled": self.companion.emotion_enabled,
                "guardian_enabled": self.companion.guardian_enabled,
                "user_model_enabled": self.companion.user_model_enabled,
            },
            "enabled_plugins": self.enabled_plugins,
            "disabled_plugins": self.disabled_plugins,
            "session_timeout": self.session_timeout,
            "max_history": self.max_history,
        }

        with open(save_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

        logger.info(f"配置已保存至: {save_path}")
