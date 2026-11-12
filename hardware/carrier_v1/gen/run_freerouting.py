#!/usr/bin/env python3
"""Place-clean board → Specctra DSN → FreeRouting → import SES → save PCB.

Requires:
  - KiCad python with pcbnew
  - Java + hardware/carrier_v1/tools/freerouting.jar

Steps (separate process-safe):
  python run_freerouting.py export
  python run_freerouting.py route
  python run_freerouting.py import
  python run_freerouting.py          # all three
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pcbnew

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "carrier_v1.kicad_pcb"
OUT = ROOT / "out"
JAR = ROOT / "tools" / "freerouting.jar"
DSN = OUT / "carrier_v1.dsn"
SES = OUT / "carrier_v1.ses"


def clear_tracks(board) -> None:
    # Prefer bulk delete when available (KiCad 10 SWIG can leak on Remove)
    if hasattr(board, "DeleteAllTracksAndVias"):
        board.DeleteAllTracksAndVias()
        return
    for t in list(board.GetTracks()):
        board.Remove(t)


def step_export() -> int:
    OUT.mkdir(exist_ok=True)
    board = pcbnew.LoadBoard(str(BOARD))
    clear_tracks(board)
    pcbnew.SaveBoard(str(BOARD), board)
    if not pcbnew.ExportSpecctraDSN(board, str(DSN)):
        print("DSN export failed", file=sys.stderr)
        return 1
    print(f"DSN bytes={DSN.stat().st_size} -> {DSN}")
    return 0


def step_route() -> int:
    if not JAR.exists():
        print(f"Missing {JAR}", file=sys.stderr)
        return 2
    if not DSN.exists():
        print(f"Missing DSN {DSN}", file=sys.stderr)
        return 1
    cmd = [
        "java",
        "-jar",
        str(JAR),
        "--gui.enabled=false",
        "-de",
        str(DSN),
        "-do",
        str(SES),
    ]
    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd)
    if not SES.exists() or SES.stat().st_size < 100:
        print("SES missing/empty", file=sys.stderr)
        return 1
    print(f"SES bytes={SES.stat().st_size} -> {SES}")
    return 0


def step_import() -> int:
    if not SES.exists():
        print(f"Missing SES {SES}", file=sys.stderr)
        return 1
    board = pcbnew.LoadBoard(str(BOARD))
    clear_tracks(board)
    if not pcbnew.ImportSpecctraSES(board, str(SES)):
        print("SES import failed", file=sys.stderr)
        return 1
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(BOARD), board)
    n = len(list(board.GetTracks())) if hasattr(board, "GetTracks") else -1
    print(f"OK tracks≈{n} -> {BOARD}")
    return 0


def main() -> int:
    args = sys.argv[1:] or ["all"]
    step = args[0]
    if step == "export":
        return step_export()
    if step == "route":
        return step_route()
    if step == "import":
        return step_import()
    if step == "all":
        # Re-invoke self in fresh interpreters so pcbnew SWIG state stays clean
        py = sys.executable
        script = str(Path(__file__).resolve())
        for s in ("export", "route", "import"):
            print(f"=== {s} ===")
            r = subprocess.call([py, script, s])
            if r != 0:
                return r
        return 0
    print(f"Unknown step {step}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
