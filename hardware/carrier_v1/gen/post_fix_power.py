#!/usr/bin/env python3
"""After FreeRouting: wipe zones and recreate power pours with correct nets (non-overlapping)."""
from __future__ import annotations

import sys
from pathlib import Path

import pcbnew
from pcbnew import VECTOR2I, FromMM, F_Cu, B_Cu, ZONE_CONNECTION_FULL, ToMM

BOARD_PATH = Path(__file__).resolve().parents[1] / "carrier_v1.kicad_pcb"
W, H = 170.0, 120.0

# Must match build_board_v14.py — no F.Cu GND overlapping VBAT
ZONE_SPECS = [
    ("GND", B_Cu, [(1.5, 1.5), (W - 1.5, 1.5), (W - 1.5, H - 1.5), (1.5, H - 1.5)], 0.35),
    ("VBAT", F_Cu, [(4, 4), (26, 4), (26, 20), (4, 20)], 0.45),
    ("VBAT_F", F_Cu, [(28, 4), (48, 4), (48, 20), (28, 20)], 0.45),
    ("VM", F_Cu, [(4, 36), (28, 36), (28, 104), (4, 104)], 0.45),
    ("V_SERVO", F_Cu, [(154, 8), (168, 8), (168, 42), (154, 42)], 0.45),
]


def net_code(board, name: str) -> int:
    info = board.GetNetInfo()
    existing = info.GetNetItem(name)
    if existing:
        return existing.GetNetCode()
    item = pcbnew.NETINFO_ITEM(board, name)
    board.Add(item)
    return item.GetNetCode()


def clear_zones(board) -> int:
    n = 0
    # Prefer bulk API when present
    if hasattr(board, "Zones"):
        for z in list(board.Zones()):
            board.Delete(z)
            n += 1
    return n


def add_zone(board, name, layer, pts, clearance):
    z = pcbnew.ZONE(board)
    code = net_code(board, name)
    ni = board.GetNetInfo().GetNetItem(name)
    z.SetNetCode(code)
    if ni and hasattr(z, "SetNet"):
        z.SetNet(ni)
    z.SetLayer(layer)
    z.SetLocalClearance(FromMM(clearance))
    z.SetMinThickness(FromMM(0.3))
    z.SetPadConnection(ZONE_CONNECTION_FULL)
    try:
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    except Exception:
        pass
    poly = z.Outline()
    poly.RemoveAllContours()
    poly.NewOutline()
    for x, y in pts:
        poly.Append(FromMM(x), FromMM(y))
    board.Add(z)
    z.SetNetCode(code)
    if ni and hasattr(z, "SetNet"):
        z.SetNet(ni)


def main() -> int:
    board = pcbnew.LoadBoard(str(BOARD_PATH))
    # Drop freerouted thin GND F.Cu segs — B.Cu pour + PTH handles ground
    gnd_rm = 0
    for t in list(board.GetTracks()):
        if t.GetNetname() != "GND":
            continue
        if isinstance(t, pcbnew.PCB_VIA):
            continue
        if t.GetLayer() == F_Cu:
            board.Delete(t)
            gnd_rm += 1
    removed = clear_zones(board)
    for name, layer, pts, clr in ZONE_SPECS:
        add_zone(board, name, layer, pts, clr)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(BOARD_PATH), board)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(BOARD_PATH), board)

    zones = [(z.GetNetname(), z.GetLayer()) for z in board.Zones()]
    from collections import defaultdict

    ws = defaultdict(set)
    for t in board.GetTracks():
        if isinstance(t, pcbnew.PCB_VIA):
            continue
        n = t.GetNetname()
        if n in ("VBAT", "VBAT_F", "VM_PRE", "VM", "V_SERVO", "GND", "+3V3", "+5V_LOGIC", "S3_5V"):
            ws[n].add(round(ToMM(t.GetWidth()), 3))
    print(f"removed {gnd_rm} F.Cu GND tracks; zones recreated (removed {removed}): {zones}")
    print("widths", {k: sorted(v) for k, v in ws.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
