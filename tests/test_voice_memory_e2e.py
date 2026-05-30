from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.integration
def test_voice_memory_e2e_script_runs() -> None:
    if not os.environ.get("SHUXIN_RUN_VOICE_E2E"):
        pytest.skip("set SHUXIN_RUN_VOICE_E2E=1 to run live memory E2E against DATABASE_URL")
    if not os.environ.get("DATABASE_URL", "").strip():
        pytest.skip("DATABASE_URL is required for voice memory E2E")

    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "test_voice_memory_e2e.py"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    assert result.returncode == 0, result.stderr or result.stdout
    assert "PASS" in result.stdout
