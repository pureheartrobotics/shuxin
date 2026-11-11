from __future__ import annotations

import asyncio
import base64
import hmac
import json
import socket
import sys
import types
from urllib.parse import parse_qs, urlparse

from shuxin.voice.config.config import ProviderConfig
from shuxin.voice.integrations.tencent_realtime_asr import (
    PCM_16K_200MS_BYTES,
    TencentRealtimeASRSession,
    build_tencent_realtime_asr_url,
    is_tencent_realtime_stt,
    parse_tencent_realtime_asr_message,
    transcribe_pcm16,
)


def test_build_tencent_realtime_asr_url_signs_sorted_query(monkeypatch):
    monkeypatch.setenv("TENCENTCLOUD_SECRET_ID", "sid")
    monkeypatch.setenv("TENCENTCLOUD_SECRET_KEY", "skey")
    monkeypatch.setattr("shuxin.voice.integrations.tencent_realtime_asr.random.randint", lambda *_: 123)
    config = ProviderConfig(type="tencent-realtime", appid="app-001", model="16k_zh")

    url = build_tencent_realtime_asr_url(config, voice_id="voice-001", now=1000)

    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    assert parsed.scheme == "wss"
    assert parsed.netloc == "asr.cloud.tencent.com"
    assert parsed.path == "/asr/v2/app-001"
    assert params["engine_model_type"] == ["16k_zh"]
    assert params["secretid"] == ["sid"]
    assert "skey" not in url

    unsigned = parsed.query.rsplit("&signature=", 1)[0]
    expected = base64.b64encode(
        hmac.new(
            b"skey",
            f"asr.cloud.tencent.com/asr/v2/app-001?{unsigned}".encode("utf-8"),
            "sha1",
        ).digest()
    ).decode("utf-8")
    assert params["signature"] == [expected]


def test_parse_tencent_realtime_asr_message_states():
    partial = parse_tencent_realtime_asr_message(
        json.dumps({"code": 0, "result": {"slice_type": 1, "voice_text_str": "你好"}})
    )
    final = parse_tencent_realtime_asr_message(
        json.dumps(
            {
                "code": 0,
                "final": 1,
                "result": {"slice_type": 2, "voice_text_str": "你好初心"},
            }
        )
    )

    assert partial.text == "你好"
    assert not partial.is_sentence_final
    assert final.final_text == "你好初心"
    assert final.is_sentence_final
    assert final.is_stream_final


def test_tencent_realtime_asr_session_chunks_audio_and_sends_end():
    class FakeWebSocket:
        def __init__(self):
            self.sent = []
            self.closed = False

        async def send(self, payload):
            self.sent.append(payload)

        async def close(self):
            self.closed = True

    async def run():
        websocket = FakeWebSocket()
        session = TencentRealtimeASRSession(
            ProviderConfig(type="tencent-realtime"),
            on_result=lambda _result: None,
        )
        session._websocket = websocket
        await session.send_audio(b"a" * (PCM_16K_200MS_BYTES + 10))
        await session.finish()
        return websocket

    websocket = asyncio.run(run())

    assert websocket.sent[0] == b"a" * PCM_16K_200MS_BYTES
    assert websocket.sent[1] == b"a" * 10
    assert websocket.sent[2] == '{"type": "end"}'
    assert websocket.closed


def test_tencent_realtime_asr_finish_does_not_wait_forever_for_reader():
    class FakeWebSocket:
        def __init__(self):
            self.sent = []
            self.closed = False

        async def send(self, payload):
            self.sent.append(payload)

        async def close(self):
            self.closed = True

    async def hang():
        await asyncio.sleep(5)

    async def run():
        websocket = FakeWebSocket()
        session = TencentRealtimeASRSession(
            ProviderConfig(type="tencent-realtime"),
            on_result=lambda _result: None,
        )
        session._websocket = websocket
        session._last_text = "你好"
        session._reader_task = asyncio.create_task(hang())
        started = asyncio.get_event_loop().time()
        text = await session.finish()
        elapsed = asyncio.get_event_loop().time() - started
        return text, elapsed, websocket.closed

    text, elapsed, closed = asyncio.run(run())
    assert text == "你好"
    assert elapsed < 2.2
    assert closed


def test_tencent_realtime_stt_type_detection():
    assert is_tencent_realtime_stt(ProviderConfig(type="tencent-realtime"))
    assert is_tencent_realtime_stt(ProviderConfig(type="tencent-asr-realtime"))
    assert not is_tencent_realtime_stt(ProviderConfig(type="local"))


def test_tencent_realtime_asr_start_connects_ipv4_without_proxy(monkeypatch):
    captured: dict = {}

    class FakeWebSocket:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        async def close(self):
            return None

    async def fake_connect(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return FakeWebSocket()

    monkeypatch.setitem(sys.modules, "websockets", types.SimpleNamespace(connect=fake_connect))
    monkeypatch.setenv("TENCENT_ASR_APPID", "app-001")
    monkeypatch.setenv("TENCENTCLOUD_SECRET_ID", "sid")
    monkeypatch.setenv("TENCENTCLOUD_SECRET_KEY", "skey")

    async def run():
        session = TencentRealtimeASRSession(
            ProviderConfig(type="tencent-realtime"),
            on_result=lambda _result: None,
        )
        await session.start()
        await session.close()

    asyncio.run(run())
    assert captured["url"].startswith("wss://asr.cloud.tencent.com/")
    assert captured["kwargs"]["family"] == socket.AF_INET
    assert captured["kwargs"]["proxy"] is None
    assert captured["kwargs"]["open_timeout"] == 8


def test_transcribe_pcm16_returns_finish_text(monkeypatch):
    class FakeSession:
        def __init__(self, config, *, on_result):
            self.pcm = b""

        async def start(self):
            return None

        async def send_audio(self, frame: bytes):
            self.pcm += frame

        async def finish(self):
            assert self.pcm == b"\x01\x00" * 16
            return "  摇头。  "

    monkeypatch.setattr(
        "shuxin.voice.integrations.tencent_realtime_asr.TencentRealtimeASRSession",
        FakeSession,
    )
    text = asyncio.run(transcribe_pcm16(ProviderConfig(type="tencent-realtime"), b"\x01\x00" * 16))
    assert text == "摇头。"
    assert asyncio.run(transcribe_pcm16(ProviderConfig(type="tencent-realtime"), b"")) == ""
