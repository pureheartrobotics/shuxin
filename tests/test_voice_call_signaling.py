"""设备通话信令集成测试（内存 fallback）。"""

from __future__ import annotations

import asyncio

import pytest

from shuxin.voice.api.call_service import CallService
from shuxin.voice.api import voice_session_registry as vsr
from shuxin.voice.persistence import call_memory


class _MockSession:
    def __init__(self, *, device_id: str, user_id: str) -> None:
        self.device_id = device_id
        self.user_id = user_id
        self.repo = None
        self.sent: list[dict] = []

    async def _send_json(self, payload: dict) -> bool:
        self.sent.append(payload)
        return True


@pytest.fixture(autouse=True)
def _reset_call_memory() -> None:
    call_memory.reset_for_tests()
    vsr._active_sessions.clear()


@pytest.fixture
def rtc_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHUXIN_RTC_CALL_ENABLED", "1")
    monkeypatch.setenv("BAIDU_RTC_APP_ID", "testapp")
    monkeypatch.setenv("BAIDU_RTC_APP_KEY", "testkey")


def test_initiate_rings_all_callee_devices(rtc_env: None) -> None:
    async def run() -> None:
        call_memory.seed_user_handle("wx_alice", "alice")
        call_memory.seed_user_handle("wx_bob", "bob")
        call_memory.seed_contact("wx_alice", "小明", "bob")
        call_memory.seed_user_devices("wx_alice", ["dev-caller"])
        call_memory.seed_user_devices("wx_bob", ["dev-bob-a", "dev-bob-b"])

        caller = _MockSession(device_id="dev-caller", user_id="wx_alice")
        callee_a = _MockSession(device_id="dev-bob-a", user_id="wx_bob")
        callee_b = _MockSession(device_id="dev-bob-b", user_id="wx_bob")
        vsr.register("dev-caller", caller)
        vsr.register("dev-bob-a", callee_a)
        vsr.register("dev-bob-b", callee_b)

        service = CallService(repo=None)
        result = await service.initiate_by_handle(
            caller_session=caller,
            target_handle="",
            contact_name="小明",
        )

        assert result["ok"] is True
        assert caller.sent and caller.sent[0]["type"] == "call/outgoing"
        assert {m["type"] for m in callee_a.sent + callee_b.sent} == {"call/ring"}
        for msg in caller.sent + callee_a.sent + callee_b.sent:
            rtc = msg.get("rtc") or {}
            assert rtc.get("token", "").startswith("004")
            assert rtc.get("room_name")

    asyncio.run(run())


def test_accept_connects_caller_and_cancels_other_ringing(rtc_env: None) -> None:
    async def run() -> None:
        call_memory.seed_user_handle("wx_alice", "alice")
        call_memory.seed_user_handle("wx_bob", "bob")
        call_memory.seed_user_devices("wx_alice", ["dev-caller"])
        call_memory.seed_user_devices("wx_bob", ["dev-bob-a", "dev-bob-b"])

        caller = _MockSession(device_id="dev-caller", user_id="wx_alice")
        callee_a = _MockSession(device_id="dev-bob-a", user_id="wx_bob")
        callee_b = _MockSession(device_id="dev-bob-b", user_id="wx_bob")
        vsr.register("dev-caller", caller)
        vsr.register("dev-bob-a", callee_a)
        vsr.register("dev-bob-b", callee_b)

        service = CallService(repo=None)
        placed = await service.initiate_by_handle(
            caller_session=caller,
            target_handle="bob",
            contact_name="",
        )
        call_id = str(placed["call_id"])

        caller.sent.clear()
        callee_a.sent.clear()
        callee_b.sent.clear()

        accepted = await service.accept(callee_a, call_id)
        assert accepted["ok"] is True

        assert any(m["type"] == "call/connected" for m in caller.sent)
        assert any(m["type"] == "call/connected" for m in callee_a.sent)
        assert any(
            m["type"] == "call/cancel" and m.get("reason") == "answered_elsewhere"
            for m in callee_b.sent
        )

    asyncio.run(run())


def test_blocked_caller_is_rejected(rtc_env: None) -> None:
    async def run() -> None:
        call_memory.seed_user_handle("wx_alice", "alice")
        call_memory.seed_user_handle("wx_bob", "bob")
        call_memory.seed_user_devices("wx_alice", ["dev-caller"])
        call_memory.seed_user_devices("wx_bob", ["dev-bob"])
        call_memory.seed_block("wx_bob", "alice")

        caller = _MockSession(device_id="dev-caller", user_id="wx_alice")
        vsr.register("dev-caller", caller)
        service = CallService(repo=None)
        result = await service.initiate_by_handle(
            caller_session=caller,
            target_handle="bob",
            contact_name="",
        )
        assert result["ok"] is False
        assert "拒接" in str(result.get("message", ""))

    asyncio.run(run())


def test_initiate_rings_via_vsr_without_binding_seed(rtc_env: None) -> None:
    """在线发现必须扫 voice_session_registry，不能依赖 call_memory 绑定种子。"""

    async def run() -> None:
        call_memory.seed_user_handle("wx_alice", "alice")
        call_memory.seed_user_handle("wx_bob", "bob")

        caller = _MockSession(device_id="dev-caller", user_id="wx_alice")
        callee = _MockSession(device_id="dev-bob", user_id="wx_bob")
        vsr.register("dev-caller", caller)
        vsr.register("dev-bob", callee)

        service = CallService(repo=None)
        result = await service.initiate_by_handle(
            caller_session=caller,
            target_handle="bob",
            contact_name="",
        )
        assert result["ok"] is True
        assert any(m["type"] == "call/ring" for m in callee.sent)

    asyncio.run(run())


def test_accept_sends_distinct_rtc_tokens(rtc_env: None) -> None:
    async def run() -> None:
        call_memory.seed_user_handle("wx_alice", "alice")
        call_memory.seed_user_handle("wx_bob", "bob")

        caller = _MockSession(device_id="dev-caller", user_id="wx_alice")
        callee = _MockSession(device_id="dev-bob", user_id="wx_bob")
        vsr.register("dev-caller", caller)
        vsr.register("dev-bob", callee)

        service = CallService(repo=None)
        placed = await service.initiate_by_handle(
            caller_session=caller,
            target_handle="bob",
            contact_name="",
        )
        call_id = str(placed["call_id"])
        caller.sent.clear()
        callee.sent.clear()

        accepted = await service.accept(callee, call_id)
        assert accepted["ok"] is True

        caller_connected = next(m for m in caller.sent if m["type"] == "call/connected")
        callee_connected = next(m for m in callee.sent if m["type"] == "call/connected")
        assert caller_connected["rtc"]["user_id"] != callee_connected["rtc"]["user_id"]
        assert caller_connected["rtc"]["token"] != callee_connected["rtc"]["token"]
        assert caller_connected["rtc"]["room_name"] == callee_connected["rtc"]["room_name"]

    asyncio.run(run())


def test_reject_notifies_caller(rtc_env: None) -> None:
    async def run() -> None:
        call_memory.seed_user_handle("wx_alice", "alice")
        call_memory.seed_user_handle("wx_bob", "bob")

        caller = _MockSession(device_id="dev-caller", user_id="wx_alice")
        callee = _MockSession(device_id="dev-bob", user_id="wx_bob")
        vsr.register("dev-caller", caller)
        vsr.register("dev-bob", callee)

        service = CallService(repo=None)
        placed = await service.initiate_by_handle(
            caller_session=caller,
            target_handle="bob",
            contact_name="",
        )
        call_id = str(placed["call_id"])
        caller.sent.clear()

        await service.reject(callee, call_id)
        assert any(
            m["type"] == "call/end" and m.get("reason") == "rejected" for m in caller.sent
        )

    asyncio.run(run())


def test_initiate_skips_dead_callee_session(rtc_env: None) -> None:
    """死连接 ring 失败时不影响其他被叫，且可被摘除。"""

    async def run() -> None:
        call_memory.seed_user_handle("wx_alice", "alice")
        call_memory.seed_user_handle("wx_bob", "bob")
        call_memory.seed_contact("wx_alice", "小明", "bob")
        call_memory.seed_user_devices("wx_alice", ["dev-caller"])
        call_memory.seed_user_devices("wx_bob", ["dev-dead", "dev-live"])

        class _DeadSession(_MockSession):
            async def _send_json(self, payload: dict) -> bool:  # type: ignore[override]
                vsr.unregister(self.device_id, self)
                return False

        caller = _MockSession(device_id="dev-caller", user_id="wx_alice")
        dead = _DeadSession(device_id="dev-dead", user_id="wx_bob")
        live = _MockSession(device_id="dev-live", user_id="wx_bob")
        vsr.register("dev-caller", caller)
        vsr.register("dev-dead", dead)
        vsr.register("dev-live", live)

        service = CallService(repo=None)
        result = await service.initiate_by_handle(
            caller_session=caller,
            target_handle="",
            contact_name="小明",
        )
        assert result["ok"] is True
        assert any(m["type"] == "call/ring" for m in live.sent)
        assert not dead.sent
        assert vsr.get_active_session("dev-dead") is None
        assert vsr.get_active_session("dev-live") is live

    asyncio.run(run())


def test_end_notifies_peer_and_leaves_media_path(rtc_env: None) -> None:
    """Web 挂断：一侧 end 后对端应收到 call/end（媒体 leave 在浏览器侧）。"""

    async def run() -> None:
        call_memory.seed_user_handle("wx_alice", "alice")
        call_memory.seed_user_handle("wx_bob", "bob")
        call_memory.seed_user_devices("wx_alice", ["dev-caller"])
        call_memory.seed_user_devices("wx_bob", ["dev-bob"])

        caller = _MockSession(device_id="dev-caller", user_id="wx_alice")
        callee = _MockSession(device_id="dev-bob", user_id="wx_bob")
        vsr.register("dev-caller", caller)
        vsr.register("dev-bob", callee)

        service = CallService(repo=None)
        placed = await service.initiate_by_handle(
            caller_session=caller,
            target_handle="bob",
            contact_name="",
        )
        call_id = str(placed["call_id"])
        assert (await service.accept(callee, call_id))["ok"] is True

        caller.sent.clear()
        callee.sent.clear()
        ended = await service.end(caller, call_id)
        assert ended["ok"] is True
        assert any(m["type"] == "call/end" for m in caller.sent)
        assert any(m["type"] == "call/end" for m in callee.sent)

    asyncio.run(run())


def test_openid_style_user_id_can_initiate(rtc_env: None) -> None:
    """防回归：text/openid 风格 user_id 不得再走 int()。"""

    async def run() -> None:
        call_memory.seed_user_handle("wx_qa_user", "qa")
        call_memory.seed_user_handle("wx_callee", "callee")
        call_memory.seed_user_devices("wx_qa_user", ["dev-qa"])
        call_memory.seed_user_devices("wx_callee", ["dev-callee"])

        caller = _MockSession(device_id="dev-qa", user_id="wx_qa_user")
        callee = _MockSession(device_id="dev-callee", user_id="wx_callee")
        vsr.register("dev-qa", caller)
        vsr.register("dev-callee", callee)

        service = CallService(repo=None)
        result = await service.initiate_by_handle(
            caller_session=caller,
            target_handle="callee",
            contact_name="",
        )
        assert result["ok"] is True
        call = call_memory.get_voice_call(str(result["call_id"]))
        assert call is not None
        assert call["caller_user_id"] == "wx_qa_user"
        assert call["callee_user_id"] == "wx_callee"

    asyncio.run(run())
