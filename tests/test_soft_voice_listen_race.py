"""Feedback loop for soft-voice first-listen race (hello.ok before recorder).

Mirrors apps/wechat-miniprogram/.../voice-ws-decode.ts ListenGateState helpers.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ListenGateState:
    ready: bool = False
    has_recorder: bool = False
    listening: bool = False
    playing: bool = False
    session_tts_active: bool = False
    pending_listen: bool = False


def request_start_listen(state: ListenGateState) -> tuple[ListenGateState, bool]:
    if state.listening or state.playing or state.session_tts_active:
        return state, False
    if not state.ready:
        return ListenGateState(**{**state.__dict__, "pending_listen": True}), False
    if not state.has_recorder:
        return ListenGateState(**{**state.__dict__, "pending_listen": True}), False
    return (
        ListenGateState(
            **{
                **state.__dict__,
                "listening": True,
                "pending_listen": False,
            }
        ),
        True,
    )


def after_recorder_ready(state: ListenGateState) -> tuple[ListenGateState, bool]:
    next_state = ListenGateState(**{**state.__dict__, "has_recorder": True})
    if not next_state.pending_listen:
        return next_state, False
    return request_start_listen(next_state)


def test_bug_hello_ok_before_recorder_emits_nothing_without_pending():
    """Regression shape of the broken client: startListen silently no-ops."""
    state = ListenGateState(ready=True, has_recorder=False)
    # Old startListen: if not ready or not recorder: return  (no pending)
    emitted = False
    if state.ready and state.has_recorder and not state.listening:
        emitted = True
    assert not emitted
    state = ListenGateState(**{**state.__dict__, "has_recorder": True})
    # Nobody retries → no listen start (user sees 请说话 but no STT)
    assert not state.listening


def test_pending_listen_recovers_after_setup_recorder():
    state = ListenGateState(ready=True, has_recorder=False)
    state, emitted = request_start_listen(state)
    assert not emitted
    assert state.pending_listen
    state, emitted = after_recorder_ready(state)
    assert emitted
    assert state.listening
    assert not state.pending_listen


def test_setup_recorder_first_then_ok_emits_immediately():
    """Preferred connect() order: recorder before waiting for hello.ok."""
    state = ListenGateState(ready=False, has_recorder=True)
    state = ListenGateState(**{**state.__dict__, "ready": True})
    state, emitted = request_start_listen(state)
    assert emitted
    assert state.listening


def test_utf8_json_arraybuffer_probe():
    raw = bytearray('{"type":"stt","state":"partial","text":"你好"}'.encode("utf-8"))
    assert raw[0] == ord("{")
    text = raw.decode("utf-8")
    import json

    data = json.loads(text)
    assert data["type"] == "stt"
    # binary mp3-like should not start with {
    assert bytearray(b"\xff\xfb\x90")[0] != ord("{")
