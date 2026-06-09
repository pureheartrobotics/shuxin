from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path


def test_compose_uses_host_data_dir_env_vars() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    for key in (
        "SHUXIN_HOST_DATA_DIR",
        "SHUXIN_HOST_MODELS_DIR",
        "SHUXIN_HOST_SAMPLES_DIR",
        "SHUXIN_HOST_OUTPUTS_DIR",
    ):
        assert key in compose


def test_prod_compose_drops_dev_source_mounts() -> None:
    prod = Path("docker-compose.prod.yml").read_text(encoding="utf-8")
    assert "SHUXIN_HOST_DATA_DIR" in prod
    assert "./src" not in prod
    assert "./scripts" not in prod
    assert "./tests" not in prod


def test_redeploy_loads_host_data_dirs() -> None:
    script = Path("scripts/redeploy_docker.sh").read_text(encoding="utf-8")
    lib = Path("scripts/lib/docker_compose.sh").read_text(encoding="utf-8")
    assert "load_host_data_dirs" in lib
    assert "load_host_data_dirs" in script
    assert "compose_cmd" in script


def test_compose_cmd_supports_multiple_compose_files() -> None:
    lib = Path("scripts/lib/docker_compose.sh").read_text(encoding="utf-8")
    assert "IFS=':'" in lib
    assert "compose_cmd" in lib


def test_export_pack_uses_host_data_dirs() -> None:
    export = Path("scripts/export_pack.sh").read_text(encoding="utf-8")
    assert "load_host_data_dirs" in export
    assert "SHUXIN_HOST_DATA_DIR" in export
    assert "_pack_host_dir" in export


def test_load_host_data_dirs_succeeds_under_set_e_without_host_vars() -> None:
    """Regression: empty SHUXIN_HOST_* in .env must not make set -e scripts exit 1."""
    lib = Path("scripts/lib/docker_compose.sh").resolve()
    root = lib.parent.parent.parent
    with tempfile.TemporaryDirectory() as tmp:
        env_file = Path(tmp) / ".env"
        env_file.write_text("OPENAI_API_KEY=sk-test\n", encoding="utf-8")
        script = (
            "set -euo pipefail\n"
            f"cd {tmp!r}\n"
            f"source {str(lib)!r}\n"
            "load_host_data_dirs\n"
            'test "$SHUXIN_HOST_DATA_DIR" = "./data"\n'
        )
        proc = subprocess.run(
            ["bash", "-c", script],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr or proc.stdout


def test_load_helpers_end_with_explicit_return_zero() -> None:
    lib = Path("scripts/lib/docker_compose.sh").read_text(encoding="utf-8")
    for fn in ("load_postgres_env", "load_voice_port", "load_host_data_dirs"):
        assert re.search(rf"{fn}\(\).*?return 0", lib, re.DOTALL), fn
