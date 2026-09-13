"""Bootstrap PYTHONPATH so the RK3566 client can import shuxin.voice.audio.opus_codec."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(APP))

from shuxin_rk3566.main import main

if __name__ == "__main__":
    main()
