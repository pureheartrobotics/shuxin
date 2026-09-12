"""scenario_runner YAML 加载测试。"""

from __future__ import annotations

from shuxin.testing.scenario_runner import load_all_scenario_files, load_scenarios, repo_root


def test_repo_root_has_e2e_data() -> None:
    assert (repo_root() / "data" / "e2e" / "memory_scenarios.yaml").exists()


def test_load_smoke_scenarios() -> None:
    scenarios = load_all_scenario_files(suite="smoke")
    ids = [s["id"] for s in scenarios]
    assert "interview_recall" in ids
    assert "infj_resist_entp_push" in ids


def test_load_full_includes_progressive() -> None:
    path = repo_root() / "data" / "e2e" / "memory_scenarios.yaml"
    full = load_scenarios(path, suite="full")
    ids = [s["id"] for s in full]
    assert "progressive_hangzhou" in ids
    assert "evergreen_profile_recall" in ids
