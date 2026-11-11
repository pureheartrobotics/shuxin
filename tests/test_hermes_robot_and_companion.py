from __future__ import annotations

from shuxin.core.config import Config
from shuxin.integrations.hermes.robot_tools import (
    RobotSessionBridge,
    bind_robot_session,
    reset_robot_session,
)
from shuxin.integrations.hermes.seed import seed_hermes_skills
from shuxin.plugins.companion import CompanionPlugin


def test_companion_does_not_inject_self_esteem_by_default(tmp_path) -> None:
    plugin = CompanionPlugin(data_dir=tmp_path)
    plugin.initialize()
    block = plugin.on_pre_llm_call(agent=None) or ""
    assert "自尊" not in block
    assert "情感" in block or "喜悦" in block


def test_companion_silence_stays_off_when_esteem_disabled(tmp_path) -> None:
    plugin = CompanionPlugin(data_dir=tmp_path, self_esteem_enabled=False)
    plugin.initialize()
    plugin.self_esteem.state.is_silent = True
    out = plugin.on_transform_output(content="原始回复", agent=None)
    assert out == "原始回复"


def test_seed_robot_skills(tmp_path) -> None:
    names = seed_hermes_skills(tmp_path / "hermes")
    assert "robot-drive" in names
    assert "robot-look" in names
    assert "robot-head" in names
    assert "life-map" in names
    assert (tmp_path / "hermes" / "skills" / "robot-drive" / "SKILL.md").is_file()


def test_robot_drive_and_head_tools() -> None:
    calls: list[tuple[str, dict]] = []
    bridge = RobotSessionBridge(
        call_mcp=lambda name, args: calls.append((name, args)) or "轮子已经动了。",
        wait_vision=lambda _timeout: None,
        caption=lambda _jpeg, _q: "看见桌子",
        has_tool=lambda _name: True,
    )
    token = bind_robot_session(bridge)
    try:
        from shuxin.integrations.hermes import robot_tools as rt

        assert "动了" in rt._drive({"action": "forward", "duration": 1.2, "speed": 0.55})
        assert calls[0][0] == "chassis"
        assert calls[0][1]["action"] == "go_forward"
        rt._head({"action": "nod"})
        assert calls[-1][0] == "self.head.nod"
        rt._head({"action": "turn", "pan": 48, "tilt": 90})
        assert calls[-1][0] == "self.head.turn"
        assert calls[-1][1]["pan"] == 48
    finally:
        reset_robot_session(token)


def test_robot_look_uses_caption() -> None:
    bridge = RobotSessionBridge(
        call_mcp=lambda _name, _args: "ok",
        wait_vision=lambda _timeout: b"\xff\xd8fake",
        caption=lambda _jpeg, question: f"画面:{question}",
        has_tool=lambda _name: True,
    )
    token = bind_robot_session(bridge)
    try:
        from shuxin.integrations.hermes import robot_tools as rt

        assert rt._look_around({"question": "前面有什么"}) == "画面:前面有什么"
    finally:
        reset_robot_session(token)


def test_config_self_esteem_defaults_off() -> None:
    assert Config().companion.self_esteem_enabled is False
