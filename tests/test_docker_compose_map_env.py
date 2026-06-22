from pathlib import Path


def test_docker_compose_passes_baidu_map_env():
    compose = Path(__file__).resolve().parents[1] / "docker-compose.yml"
    text = compose.read_text(encoding="utf-8")
    assert "SHUXIN_BAIDU_MAP_AK:" in text
    assert "SHUXIN_MAP_MCP_URL:" in text
    assert "SHUXIN_MAP_GATE_ENABLED:" in text
    assert "SHUXIN_MAP_DEFAULT_REGION:" in text
