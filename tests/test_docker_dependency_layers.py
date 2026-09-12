from __future__ import annotations

from pathlib import Path


def test_voice_dependencies_are_grouped_by_capability() -> None:
    heavy = Path("requirements-voice-heavy.txt").read_text(encoding="utf-8")
    app = Path("requirements-voice-app.txt").read_text(encoding="utf-8")

    assert "numpy==1.26.4" in heavy
    assert "pydub==0.25.1" in heavy
    assert "funasr==1.2.7" in heavy
    assert "edge-tts==7.2.6" in app
    assert "fastapi==0.115.6" in app
    assert "websockets==13.1" in app
    assert "opuslib_next" in app
    assert "Pillow==10.4.0" in app
    assert "mem0ai>=" in app
    assert "librosa==0.10.2" in app

    assert "torch" not in app
    assert "edge-tts" not in heavy


def test_voice_stack_includes_heavy_and_app() -> None:
    stack = Path("requirements-voice-stack.txt").read_text(encoding="utf-8")
    assert "-r requirements-voice-heavy.txt" in stack
    assert "-r requirements-voice-app.txt" in stack


def test_dockerfile_installs_dependency_modules_in_cache_friendly_order() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "--mount=type=cache,target=/root/.cache/pip" in dockerfile
    assert "requirements-voice-heavy.txt" in dockerfile
    assert "requirements-voice-app.txt" in dockerfile

    heavy_marker = "requirements-voice-heavy.txt"
    app_marker = "requirements-voice-app.txt"
    src_marker = "COPY src ./src"

    heavy_idx = dockerfile.index(heavy_marker)
    app_idx = dockerfile.index(app_marker)
    src_idx = dockerfile.index(src_marker)
    assert heavy_idx < app_idx < src_idx


def test_legacy_requirements_aliases_removed() -> None:
    legacy = (
        "requirements-voice-audio.txt",
        "requirements-voice-asr.txt",
        "requirements-voice-memory.txt",
        "requirements-voice-fx.txt",
        "requirements-voice-tts.txt",
        "requirements-shuxin-core.txt",
        "requirements-voice-server.txt",
        "requirements-voice-cloud.txt",
        "requirements-voice-device.txt",
        "requirements-voice-web.txt",
        "requirements-voice-dsp.txt",
    )
    for name in legacy:
        assert not Path(name).exists(), f"legacy alias should be removed: {name}"


def test_dockerignore_excludes_runtime_mounts_from_build_context() -> None:
    dockerignore = Path(".dockerignore").read_text(encoding="utf-8")

    assert "data" in dockerignore
    assert "models" in dockerignore
    assert "samples" in dockerignore
    assert "outputs" in dockerignore
