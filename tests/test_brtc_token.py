"""百度 RTC token 签发测试。"""

from shuxin.voice.brtc_token import generate_rtc_token


def test_generate_rtc_token_deterministic() -> None:
    token = generate_rtc_token(
        app_id="testapp",
        app_key="testkey",
        room_name="room8000",
        user_id="1008",
        ttl_seconds=3600,
        now_ts=1544766061,
        random_hex="a1b2c3d4",
    )
    assert token.startswith("004")
    assert "1544766061" in token
    token2 = generate_rtc_token(
        app_id="testapp",
        app_key="testkey",
        room_name="room8000",
        user_id="1008",
        ttl_seconds=3600,
        now_ts=1544766061,
        random_hex="a1b2c3d4",
    )
    assert token == token2
