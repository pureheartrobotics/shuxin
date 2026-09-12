from __future__ import annotations

import time
from types import SimpleNamespace

from shuxin.plugins.companion import CompanionPlugin


def test_companion_softens_silent_response_for_voice_channel(tmp_path) -> None:
    plugin = CompanionPlugin(data_dir=tmp_path)
    plugin.initialize()
    plugin.self_esteem.state.is_silent = True
    plugin.self_esteem.state.silent_start = time.time()
    agent = SimpleNamespace(context=SimpleNamespace(metadata={"channel": "voice"}))

    response = plugin.on_transform_output(agent=agent, content="原始回复")

    assert response is not None
    assert "缓一下" in response
    assert "不舒服" not in response
