#!/usr/bin/env python3
"""Place-clean board → Specctra DSN → FreeRouting → import SES → save PCB.

Requires:
  - KiCad python with pcbnew
  - Java + hardware/carrier_v1/tools/freerouting.jar
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


def main() -> int:
    OUT.mkdir(exist_ok=True)
    if not JAR.exists():
        print(f"Missing {JAR} — download freerouting-2.1.0.jar into tools/", file=sys.stderr)
        return 2

    board = pcbnew.LoadBoard(str(BOARD))
    for t in list(board.GetTracks()):
        board.Remove(t)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(BOARD), board)

    if not pcbnew.ExportSpecctraDSN(board, str(DSN)):
        print("DSN export failed", file=sys.stderr)
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
        "--router.autorouter.max_passes=80",
    ]
    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd)

    board = pcbnew.LoadBoard(str(BOARD))
    for t in list(board.GetTracks()):
        board.Remove(t)
    if not pcbnew.ImportSpecctraSES(board, str(SES)):
        print("SES import failed", file=sys.stderr)
        return 1
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(BOARD), board)
    print(f"OK tracks={len(list(board.GetTracks()))} -> {BOARD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
