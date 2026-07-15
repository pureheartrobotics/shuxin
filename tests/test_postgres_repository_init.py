from __future__ import annotations

from unittest.mock import MagicMock

from shuxin.voice.persistence.postgres_repository import VoicePostgresRepository


def test_voice_postgres_repository_exposes_sub_repos() -> None:
    repo = VoicePostgresRepository(MagicMock())
    assert hasattr(repo, "memory")
    assert hasattr(repo, "mall")
    assert hasattr(repo, "devices")
    assert hasattr(repo, "users")
