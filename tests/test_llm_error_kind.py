from __future__ import annotations

from shuxin.core.agent import classify_llm_error


def test_classify_llm_error_connect_timeout() -> None:
    assert classify_llm_error(TimeoutError("connect timed out")) == "connect_timeout"


def test_classify_llm_error_auth() -> None:
    class FakeAuthError(Exception):
        pass

    assert classify_llm_error(FakeAuthError("401 Unauthorized")) == "auth_error"


def test_classify_llm_error_unknown() -> None:
    assert classify_llm_error(RuntimeError("boom")) == "llm_error"
