"""mbti_scorer 单元测试。"""

from __future__ import annotations

from shuxin.testing.mbti_scorer import extract_verbal_markers, load_mbti_profiles, score_mbti_fidelity


def test_load_mbti_profiles() -> None:
    profiles = load_mbti_profiles()
    assert "INFJ" in profiles
    assert "ENTP" in profiles


def test_extract_verbal_markers_infj() -> None:
    profiles = load_mbti_profiles()
    markers = extract_verbal_markers(profiles["INFJ"])
    assert any("我有一种感觉" in m for m in markers)


def test_score_mbti_fidelity_hit() -> None:
    reply = "我有一种感觉，你也许也感受到了，这件事对你来说不容易。"
    result = score_mbti_fidelity(reply, "INFJ", min_hits=1)
    assert result["pass"] is True
    assert result["hit_count"] >= 1


def test_score_mbti_fidelity_miss() -> None:
    reply = "好的，收到。按步骤执行即可。"
    result = score_mbti_fidelity(reply, "INFJ", min_hits=1)
    assert result["pass"] is False


def test_score_mbti_fidelity_entp() -> None:
    profiles = load_mbti_profiles()
    markers = extract_verbal_markers(profiles["ENTP"])
    if markers:
        reply = markers[0] + "我们换个角度想想？"
        result = score_mbti_fidelity(reply, "ENTP", profiles=profiles, min_hits=1)
        assert result["pass"] is True
