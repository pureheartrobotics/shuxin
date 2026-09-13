from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "rk3566"))

from shuxin_rk3566.actions import extract_actions, spoken_text
from shuxin_rk3566.chassis import MockChassis, MotionController
from shuxin_rk3566.config import DeviceRuntimeConfig
from shuxin_rk3566.motion_intent import MotionCommand, parse_motion_intent


def test_extract_actions_keeps_order() -> None:
    text = "（耳朵微微竖起）你还好吗？（轻轻靠近）"
    assert extract_actions(text) == ["耳朵微微竖起", "轻轻靠近"]
    assert spoken_text(text) == "你还好吗？"


def test_pure_action_sentence() -> None:
    text = "（眼睛笑成月牙，轻轻蹭了蹭你）"
    assert extract_actions(text) == ["眼睛笑成月牙，轻轻蹭了蹭你"]
    assert spoken_text(text) == ""


def test_device_runtime_config_from_env(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_VOICE_WS_URL", "ws://10.0.0.8:8765/ws/voice")
    monkeypatch.setenv("SHUXIN_DEVICE_CODE", "SX-000001")
    monkeypatch.setenv("SHUXIN_DEVICE_SECRET", "secret-value")
    monkeypatch.setenv("SHUXIN_DEVICE_CLIENT_ID", "rk3566-lab")
    config = DeviceRuntimeConfig.from_env()
    assert config.ws_url.endswith("/ws/voice")
    assert config.device_code == "SX-000001"
    assert config.device_secret == "secret-value"
    assert config.client_id == "rk3566-lab"


def test_parse_motion_commands() -> None:
    assert parse_motion_intent("往前走一点").action == "forward"
    assert parse_motion_intent("往前走一点").duration_s == 0.8
    assert parse_motion_intent("快速后退两秒").action == "backward"
    assert parse_motion_intent("快速后退两秒").duration_s == 2.0
    assert parse_motion_intent("快速后退两秒").speed == 0.85
    assert parse_motion_intent("向左转").action == "left"
    assert parse_motion_intent("右转").action == "right"
    assert parse_motion_intent("转一圈").action == "spin"
    assert parse_motion_intent("停下").action == "stop"
    assert parse_motion_intent("过来").action == "forward"
    assert parse_motion_intent("你好初心") is None
    assert parse_motion_intent("") is None


def test_stop_has_priority_over_forward() -> None:
    command = parse_motion_intent("停，不要往前走")
    assert command is not None
    assert command.action == "stop"


def test_motion_controller_stop_cancels_forward() -> None:
    async def body() -> None:
        chassis = MockChassis()
        controller = MotionController(chassis)
        await controller.handle(
            MotionCommand("forward", duration_s=3.0, speed=0.5, source_text="前进")
        )
        await asyncio.sleep(0.05)
        await controller.handle(
            MotionCommand("stop", duration_s=0.0, speed=0.0, source_text="停")
        )
        await asyncio.sleep(0.05)
        assert controller.last_command is not None
        assert controller.last_command.action == "stop"

    asyncio.run(body())
