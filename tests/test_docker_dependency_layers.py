from __future__ import annotations

from pathlib import Path


def test_barcode_dependencies_are_installed_in_late_docker_layer() -> None:
    voice_extra = Path("requirements-voice-extra.txt").read_text(encoding="utf-8")
    late_extra = Path("requirements-voice-dev-extra.txt").read_text(encoding="utf-8")
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "Pillow" not in voice_extra
    assert "zxing-cpp" not in voice_extra
    assert "Pillow==10.4.0" in late_extra
    assert "zxing-cpp==2.2.0" in late_extra
    assert "COPY requirements-voice-dev-extra.txt ./" in dockerfile
    assert "pip install --no-cache-dir -r requirements-voice-dev-extra.txt" in dockerfile
    assert dockerfile.index("requirements-voice-dev-extra.txt") > dockerfile.index(
        "requirements-shuxin-core.txt"
    )
    assert dockerfile.index("requirements-voice-dev-extra.txt") < dockerfile.index("COPY src ./src")


def test_redeploy_hash_tracks_late_voice_dependencies() -> None:
    script = Path("scripts/redeploy_docker.sh").read_text(encoding="utf-8")

    assert "requirements-voice-dev-extra.txt" in script
    assert 'PROJECT_NAME="${PROJECT_NAME:-shuxin}"' in script
