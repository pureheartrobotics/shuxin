from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
DEFAULT_USER_ID = "demo-user"
DEFAULT_AUDIO_QUOTA_MB = 512


@dataclass(frozen=True)
class UserSettings:
    """Web 语音测试台的用户级配置。

    v1 用 YAML 模拟后台用户系统，只保存鉴权 token 和音频额度。
    """

    user_id: str
    token: str = ""
    audio_quota_mb: int = DEFAULT_AUDIO_QUOTA_MB
    llm_config: dict[str, Any] | None = None
    agent_id: str = ""

    @property
    def audio_quota_bytes(self) -> int:
        """把 MB 单位额度转换成字节，并保证最小值大于 0。"""
        return max(1, self.audio_quota_mb) * 1024 * 1024


class UserConfigProvider:
    """从类后台 YAML 文件加载用户鉴权和额度配置。

    配置文件支持热加载：文件 mtime 变化后，下一次读取会自动刷新。
    未来替换为数据库或远程管理 API 时，可以保持 `get/authenticate`
    这两个调用面不变。
    """

    def __init__(self, config_path: str | os.PathLike[str] | None = None) -> None:
        self.config_path = Path(
            config_path
            or os.environ.get("SHUXIN_USERS_CONFIG", "data/users.yaml")
        )
        self._mtime: float | None = None
        self._raw: dict[str, Any] = {}
        self._load_if_needed(force=True)

    def get(self, user_id: str | None) -> UserSettings:
        """读取用户配置；缺失用户会回落到默认额度和空 token。"""
        selected_id = validate_user_id(user_id or DEFAULT_USER_ID)
        self._load_if_needed()
        defaults = self._raw.get("defaults", {})
        users = self._raw.get("users", {})
        user_data = users.get(selected_id, {})

        return UserSettings(
            user_id=selected_id,
            token=str(user_data.get("token", "")),
            audio_quota_mb=int(
                user_data.get(
                    "audio_quota_mb",
                    defaults.get("audio_quota_mb", DEFAULT_AUDIO_QUOTA_MB),
                )
            ),
            llm_config=dict(user_data.get("llm_config") or defaults.get("llm_config") or {}),
        )

    def authenticate(self, user_id: str | None, token: str | None) -> UserSettings:
        """校验用户 token 并返回用户配置。

        demo-user 允许空 token，其他用户如果没有显式配置 token 则拒绝访问。
        """
        settings = self.get(user_id)
        if settings.token and token != settings.token:
            raise PermissionError("invalid user token")
        if not settings.token and settings.user_id != DEFAULT_USER_ID:
            raise PermissionError("user token is not configured")
        return settings

    def _load_if_needed(self, force: bool = False) -> None:
        """按文件修改时间懒加载 YAML，减少每条消息的磁盘读取。"""
        try:
            mtime = self.config_path.stat().st_mtime
        except FileNotFoundError:
            if force:
                self._raw = {}
                self._mtime = None
            return

        if not force and self._mtime == mtime:
            return

        with self.config_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise ValueError(f"User config must be a mapping: {self.config_path}")
        self._raw = data
        self._mtime = mtime


def validate_user_id(user_id: str) -> str:
    """校验 user/device/session 可用的安全标识，防止路径穿越。"""
    if not USER_ID_PATTERN.fullmatch(user_id):
        raise ValueError(
            "user_id must be 1-64 chars and contain only letters, digits, dot, dash or underscore"
        )
    return user_id


def now_ms() -> int:
    """返回毫秒时间戳，供后续事件或协议扩展复用。"""
    return int(time.time() * 1000)
