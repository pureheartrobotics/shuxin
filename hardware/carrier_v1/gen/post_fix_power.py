#!/usr/bin/env python3
"""After FreeRouting: ensure zones keep nets + solid pad connection; refill."""
from __future__ import annotations

import sys
from pathlib import Path

import pcbnew
from pcbnew import B_Cu, ZONE_CONNECTION_FULL, ToMM

BOARD_PATH = Path(__file__).resolve().parents[1] / "carrier_v1.kicad_pcb"


def net_code(board, name: str) -> int:
    info = board.GetNetInfo()
    existing = info.GetNetItem(name)
    if existing:
        return existing.GetNetCode()
    item = pcbnew.NETINFO_ITEM(board, name)
    board.Add(item)
    return item.GetNetCode()


def main() -> int:
    board = pcbnew.LoadBoard(str(BOARD_PATH))

    for z in board.Zones():
        if not z.GetNetname() or z.GetNetname() == "<no net>":
            if z.GetLayer() == B_Cu:
                z.SetNetCode(net_code(board, "GND"))
        z.SetPadConnection(ZONE_CONNECTION_FULL)

    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(BOARD_PATH), board)

    from collections import defaultdict

    ws = defaultdict(set)
    for t in board.GetTracks():
        if isinstance(t, pcbnew.PCB_VIA):
            continue
        n = t.GetNetname()
        if n in ("VBAT", "VBAT_F", "VM_PRE", "VM", "V_SERVO", "GND"):
            ws[n].add(round(ToMM(t.GetWidth()), 3))
    print("zone refill OK; power widths", {k: sorted(v) for k, v in ws.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
