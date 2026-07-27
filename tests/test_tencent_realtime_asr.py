from __future__ import annotations

import asyncio
import base64
import hmac
import json
from urllib.parse import parse_qs, urlparse

from shuxin.voice.config.config import ProviderConfig
from shuxin.voice.integrations.tencent_realtime_asr import (
    PCM_16K_200MS_BYTES,
    TencentRealtimeASRSession,
    build_tencent_realtime_asr_url,
    is_benign_asr_idle_error,
    is_tencent_realtime_stt,
    parse_tencent_realtime_asr_message,
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


def test_tencent_realtime_stt_type_detection():
    assert is_tencent_realtime_stt(ProviderConfig(type="tencent-realtime"))
    assert is_tencent_realtime_stt(ProviderConfig(type="tencent-asr-realtime"))
    assert not is_tencent_realtime_stt(ProviderConfig(type="local"))


def test_is_benign_asr_idle_error():
    assert is_benign_asr_idle_error("客户端超过15秒未发送音频数据")
    assert is_benign_asr_idle_error("Tencent realtime ASR failed: 未发送音频数据")
    assert not is_benign_asr_idle_error("signature error")


def test_asr_finish_cancels_hung_reader(monkeypatch):
    monkeypatch.setattr(
        "shuxin.voice.integrations.tencent_realtime_asr.ASR_FINISH_TIMEOUT_SECONDS",
        0.05,
    )

    class FakeWebSocket:
        def __init__(self):
            self.sent = []
            self.closed = False

        async def send(self, payload):
            self.sent.append(payload)

        async def close(self):
            self.closed = True

    async def hung_reader():
        await asyncio.sleep(30)

    async def run():
        websocket = FakeWebSocket()
        session = TencentRealtimeASRSession(
            ProviderConfig(type="tencent-realtime"),
            on_result=lambda _result: None,
        )
        session._websocket = websocket
        session._reader_task = asyncio.create_task(hung_reader())
        text = await session.finish()
        return websocket, text, session._reader_task

    websocket, text, reader = asyncio.run(run())
    assert websocket.closed
    assert reader is None
    assert text == ""
    assert '{"type": "end"}' in websocket.sent


def test_asr_read_loop_swallows_idle_timeout():
    class FakeWebSocket:
        def __init__(self):
            self.messages = [
                json.dumps({"code": 4000, "message": "客户端超过15秒未发送音频数据"}),
            ]
            self._i = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._i >= len(self.messages):
                raise StopAsyncIteration
            msg = self.messages[self._i]
            self._i += 1
            return msg

    async def run():
        ends = []

        async def on_end(reason, text):
            ends.append((reason, text))

        session = TencentRealtimeASRSession(
            ProviderConfig(type="tencent-realtime"),
            on_result=lambda _result: None,
            on_end=on_end,
        )
        session._websocket = FakeWebSocket()
        session._last_text = "你好"
        await session._read_loop()
        return ends

    ends = asyncio.run(run())
    assert ends == [("idle", "你好")]
