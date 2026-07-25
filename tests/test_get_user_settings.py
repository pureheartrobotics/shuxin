"""get_user_settings loads WeChat users without requiring users.token."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from shuxin.voice.persistence.user_repo import UserRepository


def test_get_user_settings_allows_empty_users_token() -> None:
    repo = UserRepository.__new__(UserRepository)
    row = {
        "user_id": "wx_abcdef",
        "token": None,
        "audio_quota_mb": 100,
        "llm_config": {"api_key": "sk-test", "model": "m"},
        "agent_id": "shuxin",
    }
    repo.pool = MagicMock()
    repo.pool.fetchrow = AsyncMock(return_value=row)

    settings = asyncio.run(repo.get_user_settings("wx_abcdef"))
    assert settings.user_id == "wx_abcdef"
    assert settings.token == ""
    assert settings.llm_config["api_key"] == "sk-test"


def test_authenticate_user_still_rejects_empty_token_for_non_demo() -> None:
    repo = UserRepository.__new__(UserRepository)
    row = {
        "user_id": "wx_abcdef",
        "token": "",
        "audio_quota_mb": 100,
        "llm_config": {},
        "agent_id": "",
    }
    repo.pool = MagicMock()
    repo.pool.fetchrow = AsyncMock(return_value=row)

    with pytest.raises(PermissionError, match="user token is not configured"):
        asyncio.run(repo.authenticate_user("wx_abcdef", ""))
