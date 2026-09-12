"""e2e_helpers 单元测试（force rebind 逻辑）。"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from shuxin.testing.e2e_helpers import _force_rebind_device, ensure_scenario_user


def _mock_repo(*, fetchrow_return: Any = None) -> MagicMock:
    repo = MagicMock()
    repo.pool = MagicMock()
    repo.pool.execute = AsyncMock()
    repo.pool.fetchrow = AsyncMock(return_value=fetchrow_return)
    repo.admin_unbind_device = AsyncMock()
    repo.admin_bind_device = AsyncMock()
    return repo


def test_force_rebind_unbound_device() -> None:
    mock_repo = _mock_repo(fetchrow_return=None)

    asyncio.run(
        _force_rebind_device(
            mock_repo, user_id="e2e-s-interview", device_id="demo-device-002"
        )
    )

    mock_repo.admin_unbind_device.assert_not_called()
    mock_repo.admin_bind_device.assert_awaited_once_with(
        user_id="e2e-s-interview", device_id="demo-device-002"
    )


def test_force_rebind_same_user() -> None:
    mock_repo = _mock_repo(
        fetchrow_return={"binding_id": "bind-1", "user_id": "e2e-s-interview"}
    )

    asyncio.run(
        _force_rebind_device(
            mock_repo, user_id="e2e-s-interview", device_id="demo-device-002"
        )
    )

    mock_repo.admin_unbind_device.assert_not_called()
    mock_repo.admin_bind_device.assert_awaited_once()


def test_force_rebind_different_user() -> None:
    mock_repo = _mock_repo(
        fetchrow_return={"binding_id": "bind-alice", "user_id": "e2e-user-alice"}
    )

    asyncio.run(
        _force_rebind_device(
            mock_repo, user_id="e2e-s-interview", device_id="demo-device-002"
        )
    )

    mock_repo.admin_unbind_device.assert_awaited_once_with(binding_id="bind-alice")
    mock_repo.admin_bind_device.assert_awaited_once_with(
        user_id="e2e-s-interview", device_id="demo-device-002"
    )


def test_ensure_scenario_user_calls_force_rebind() -> None:
    mock_repo = _mock_repo(fetchrow_return=None)
    scenario: dict[str, Any] = {
        "id": "interview_recall",
        "user_id": "e2e-s-interview",
        "device_id": "demo-device-002",
        "mbti": "INFJ",
    }

    asyncio.run(ensure_scenario_user(mock_repo, scenario))

    assert mock_repo.pool.execute.await_count == 2
    mock_repo.admin_bind_device.assert_awaited_once_with(
        user_id="e2e-s-interview", device_id="demo-device-002"
    )
