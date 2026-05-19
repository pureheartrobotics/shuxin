"""舒心配置管理模块

支持 YAML 配置文件 + 环境变量覆盖，对标 Hermes 的配置系统。

配置加载优先级（从高到低）：
1. 环境变量 (SHUXIN_*)
2. 命令行指定配置文件
3. ~/.shuxin/config.yaml
4. ./.shuxin.yaml / ./.shuxin.yml
5. 默认值
"""

from __future__ import annotations

import os
import yaml
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("shuxin.config")

# 默认配置路径
SHUXIN_HOME_ENV = "SHUXIN_HOME"
DEFAULT_SHUXIN_HOME = Path.home() / ".shuxin"


def get_shuxin_home() -> Path:
    """获取舒心家目录，优先使用环境变量。

    Returns:
        Path: 舒心家目录路径。如果设置了 ``SHUXIN_HOME`` 环境变量则使用该值，
              否则返回 ``~/.shuxin``。

    Example:
        >>> get_shuxin_home()
        PosixPath('/home/user/.shuxin')
    """
    env_home = os.environ.get(SHUXIN_HOME_ENV)
    if env_home:
        return Path(env_home)
    return DEFAULT_SHUXIN_HOME


@dataclass
class LLMConfig:
    """LLM 提供者配置。

    Attributes:
        provider: LLM 提供者类型 (openai, anthropic, custom)。
        model: 模型名称，如 gpt-4o、claude-3-opus。
        api_key: API 密钥。
        base_url: 自定义 API 地址（用于兼容 OpenAI 格式的第三方服务）。
        max_tokens: 最大生成 token 数。
        temperature: 生成温度 (0.0-2.0)，越高越随机。
        top_p: 核采样参数 (0.0-1.0)。
    """
    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7
    top_p: float = 0.9


@dataclass
class SoulConfig:
    """人格系统配置。

    Attributes:
        soul_path: SOUL.md 文件路径，为空则使用默认搜索路径。
        auto_load: 是否自动加载 SOUL.md。
    """
    soul_path: str = ""
    auto_load: bool = True


@dataclass
class CompanionConfig:
    """陪伴系统配置。

    Attributes:
        enabled: 是否启用陪伴系统。
        self_esteem_enabled: 是否启用自尊系统。
        emotion_enabled: 是否启用情感引擎。
        guardian_enabled: 是否启用守护系统。
        user_model_enabled: 是否启用用户建模。
        data_dir: 数据持久化目录，为空则使用默认路径。
    """
    enabled: bool = True
    self_esteem_enabled: bool = True
    emotion_enabled: bool = True
    guardian_enabled: bool = True
    user_model_enabled: bool = True
    data_dir: str = ""


@dataclass
class Config:
    """舒心主配置。

    管理所有子配置（LLM、人格、陪伴系统），支持从 YAML 文件加载
    和环境变量覆盖。

    Attributes:
        debug: 是否启用调试模式。
        verbose: 是否启用详细日志。
        shuxin_home: 舒心家目录路径。
        llm: LLM 提供者配置。
        soul: 人格系统配置。
        companion: 陪伴系统配置。
        enabled_plugins: 启用的插件列表。
        disabled_plugins: 禁用的插件列表。
        session_timeout: 会话超时时间（秒）。
        max_history: 最大历史消息数。
    """
    # 核心
    debug: bool = False
    verbose: bool = False
    shuxin_home: str = str(get_shuxin_home())

    # 子配置
    llm: LLMConfig = field(default_factory=LLMConfig)
    soul: SoulConfig = field(default_factory=SoulConfig)
    companion: CompanionConfig = field(default_factory=CompanionConfig)

    # 插件
    enabled_plugins: List[str] = field(default_factory=lambda: ["companion"])
    disabled_plugins: List[str] = field(default_factory=list)

    # 会话
    session_timeout: int = 3600
    max_history: int = 100

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    @classmethod
    def load(cls, path: Optional[str] = None) -> "Config":
        """从 YAML 文件加载配置，支持环境变量覆盖。

        加载优先级：
        1. 环境变量 (SHUXIN_*)
        2. 命令行指定配置文件
        3. ~/.shuxin/config.yaml
        4. ./.shuxin.yaml / ./.shuxin.yml
        5. 默认值

        Args:
            path: 可选的配置文件路径。如果提供，优先加载该文件。

        Returns:
            Config: 加载完成的配置实例。

        Example:
            >>> config = Config.load("~/.shuxin/config.yaml")
            >>> config.llm.model
            'gpt-4o'
        """
        cfg = cls()

        # 1. 尝试加载配置文件
        config_paths: List[Path] = []
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
                    if data and isinstance(data, dict):
                        cfg._merge_dict(data)
                    logger.info("已加载配置文件: %s", cp)
                    break
                except yaml.YAMLError as e:
                    logger.warning("配置文件格式错误 %s: %s", cp, e)
                except OSError as e:
                    logger.warning("无法读取配置文件 %s: %s", cp, e)
                except Exception as e:
                    logger.warning("加载配置文件失败 %s: %s", cp, e)

        # 2. 环境变量覆盖
        cfg._apply_env_overrides()

        return cfg

    def _merge_dict(self, data: Dict[str, Any]) -> None:
        """递归合并字典到配置。

        Args:
            data: 从 YAML 解析出的配置字典。

        Note:
            只合并已定义的属性，忽略未知字段。
        """
        with self._lock:
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
        """应用环境变量覆盖配置。

        支持的环境变量：
        - SHUXIN_LLM_PROVIDER → llm.provider
        - SHUXIN_LLM_MODEL → llm.model
        - SHUXIN_API_KEY → llm.api_key
        - SHUXIN_BASE_URL → llm.base_url
        - SHUXIN_DEBUG → debug (布尔值)
        - SHUXIN_VERBOSE → verbose (布尔值)

        Note:
            布尔值支持 "1"/"true"/"yes" 为 True，"0"/"false"/"no" 为 False。
        """
        env_map: Dict[str, tuple] = {
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
        """保存配置到 YAML 文件。

        Args:
            path: 保存路径。如果未提供，保存到 ``~/.shuxin/config.yaml``。

        Raises:
            OSError: 当无法创建目录或写入文件时抛出。
        """
        save_path = path or str(get_shuxin_home() / "config.yaml")
        save_dir = Path(save_path).parent
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error("无法创建配置目录 %s: %s", save_dir, e)
            raise

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

        try:
            with open(save_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
            logger.info("配置已保存至: %s", save_path)
        except OSError as e:
            logger.error("无法写入配置文件 %s: %s", save_path, e)
            raise
