from __future__ import annotations

from pathlib import Path


def test_voice_dependencies_are_grouped_by_capability() -> None:
    local = Path("requirements-voice-local.txt").read_text(encoding="utf-8")
    web = Path("requirements-voice-web.txt").read_text(encoding="utf-8")
    integrations = Path("requirements-voice-integrations.txt").read_text(encoding="utf-8")
    barcode = Path("requirements-voice-barcode.txt").read_text(encoding="utf-8")

    assert "numpy==1.26.4" in local
    assert "torch==2.2.2" in local
    assert "funasr==1.2.7" in local
    assert "fastapi==0.115.6" in web
    assert "uvicorn[standard]==0.34.0" in web
    assert "asyncpg==0.30.0" in web
    assert "websockets==13.1" in integrations
    assert "Pillow==10.4.0" in barcode
    assert "zxing-cpp==2.2.0" in barcode

    assert "Pillow" not in local + web + integrations
    assert "zxing-cpp" not in local + web + integrations
    assert "websockets" not in local + web + barcode


def test_dockerfile_installs_dependency_modules_in_cache_friendly_order() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "docker/dockerfile:" not in dockerfile
    assert "--mount=type=cache,target=/root/.cache/pip" in dockerfile
    assert "pip install -r requirements-voice-barcode.txt" in dockerfile
    assert "pip install --no-cache-dir -r requirements-voice-barcode.txt" not in dockerfile
    assert dockerfile.index("requirements-voice-local.txt") < dockerfile.index(
        "requirements-shuxin-core.txt"
    )
    assert dockerfile.index("requirements-shuxin-core.txt") < dockerfile.index(
        "requirements-voice-web.txt"
    )
    assert dockerfile.index("requirements-voice-web.txt") < dockerfile.index(
        "requirements-voice-integrations.txt"
    )
    assert dockerfile.index("requirements-voice-integrations.txt") < dockerfile.index(
        "requirements-voice-barcode.txt"
    )
    assert dockerfile.index("requirements-voice-barcode.txt") < dockerfile.index("COPY src ./src")


def test_redeploy_hash_tracks_dependency_modules() -> None:
    script = Path("scripts/redeploy_docker.sh").read_text(encoding="utf-8")

    assert "requirements-voice-local.txt" in script
    assert "requirements-shuxin-core.txt" in script
    assert "requirements-voice-web.txt" in script
    assert "requirements-voice-integrations.txt" in script
    assert "requirements-voice-barcode.txt" in script
    assert "dependency modules changed:" in script
    assert 'PROJECT_NAME="${PROJECT_NAME:-shuxin}"' in script


def test_dockerignore_excludes_runtime_mounts_from_build_context() -> None:
    dockerignore = Path(".dockerignore").read_text(encoding="utf-8")

    assert "data" in dockerignore
    assert "models" in dockerignore
    assert "samples" in dockerignore
    assert "outputs" in dockerignore
