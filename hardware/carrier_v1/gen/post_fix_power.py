#!/usr/bin/env python3
"""After FreeRouting: rebuild power/GND pours; short P3-1 GND stitch if needed."""
from __future__ import annotations

import sys
from collections import deque
from pathlib import Path

import pcbnew
from pcbnew import VECTOR2I, FromMM, ToMM, F_Cu, B_Cu, ZONE_CONNECTION_FULL

BOARD_PATH = Path(__file__).resolve().parents[1] / "carrier_v1.kicad_pcb"
W, H = 170.0, 120.0

POWER_ZONES = [
    ("VBAT", F_Cu, [(4, 4), (26, 4), (26, 20), (4, 20)], 0.45, 2),
    ("VBAT_F", F_Cu, [(28, 4), (48, 4), (48, 20), (28, 20)], 0.45, 2),
    ("VM", F_Cu, [(4, 36), (28, 36), (28, 104), (4, 104)], 0.45, 2),
    ("V_SERVO", F_Cu, [(154, 8), (168, 8), (168, 42), (154, 42)], 0.45, 2),
]


def mm(x, y):
    return VECTOR2I(FromMM(float(x)), FromMM(float(y)))


def net_code(board, name: str) -> int:
    info = board.GetNetInfo()
    existing = info.GetNetItem(name)
    if existing:
        return existing.GetNetCode()
    item = pcbnew.NETINFO_ITEM(board, name)
    board.Add(item)
    return item.GetNetCode()


def add_zone(board, name, layer, pts, clearance, priority=0):
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
        z.SetAssignedPriority(priority)
    except Exception:
        pass
    try:
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)
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


def track_keepout_b(board, pts):
    z = pcbnew.ZONE(board)
    z.SetIsRuleArea(True)
    z.SetDoNotAllowTracks(True)
    z.SetDoNotAllowVias(False)
    z.SetDoNotAllowPads(False)
    z.SetDoNotAllowFootprints(False)
    z.SetDoNotAllowZoneFills(False)
    ls = pcbnew.LSET()
    ls.AddLayer(B_Cu)
    z.SetLayerSet(ls)
    poly = z.Outline()
    poly.RemoveAllContours()
    poly.NewOutline()
    for x, y in pts:
        poly.Append(FromMM(x), FromMM(y))
    board.Add(z)


def add_track(board, net, layer, x1, y1, x2, y2, w=0.45):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(mm(x1, y1))
    t.SetEnd(mm(x2, y2))
    t.SetWidth(FromMM(w))
    t.SetLayer(layer)
    t.SetNetCode(net_code(board, net))
    board.Add(t)


def add_via(board, net, x, y, dia=0.8, drill=0.4):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(mm(x, y))
    v.SetLayerPair(F_Cu, B_Cu)
    try:
        v.SetWidth(F_Cu, FromMM(dia))
        v.SetWidth(B_Cu, FromMM(dia))
    except Exception:
        pass
    v.SetDrill(FromMM(drill))
    v.SetNetCode(net_code(board, net))
    board.Add(v)


def find_pad(board, ref: str, pad_no: str):
    for fp in board.GetFootprints():
        if fp.GetReference() != ref:
            continue
        for p in fp.Pads():
            if p.GetNumber() == pad_no:
                return p
    return None


def scrub_b_tracks_in_keepout(board) -> int:
    """FreeRouting may ignore KiCad rule areas — delete B.Cu +3V3 fencing in ENC strip only.

    Do not scrub ENC_* signal escapes here; that orphans pad stubs (see ENC_A_A regression).
    """
    box = (38.0, 86.0, 95.0, 92.0)
    xmin, ymin, xmax, ymax = box
    doomed = []
    for t in list(board.GetTracks()):
        if t.Type() == pcbnew.PCB_VIA_T or t.GetLayer() != B_Cu:
            continue
        if t.GetNetname() != "+3V3":
            continue
        x1, y1 = ToMM(t.GetStart().x), ToMM(t.GetStart().y)
        x2, y2 = ToMM(t.GetEnd().x), ToMM(t.GetEnd().y)
        if max(x1, x2) < xmin or min(x1, x2) > xmax or max(y1, y2) < ymin or min(y1, y2) > ymax:
            continue
        doomed.append(t)
    for t in doomed:
        if hasattr(board, "Delete"):
            board.Delete(t)
        else:
            board.Remove(t)
    return len(doomed)


def main() -> int:
    board = pcbnew.LoadBoard(str(BOARD_PATH))

    scrubbed = scrub_b_tracks_in_keepout(board)
    print(f"scrubbed B.Cu tracks in ENC keepout={scrubbed}")

    # Drop copper zones only; keep rule-area keepouts
    for z in list(board.Zones()):
        if z.GetIsRuleArea():
            continue
        board.Delete(z)

    add_zone(
        board,
        "GND",
        B_Cu,
        [(1.5, 1.5), (W - 1.5, 1.5), (W - 1.5, H - 1.5), (1.5, H - 1.5)],
        0.35,
        0,
    )
    for name, layer, pts, clr, pri in POWER_ZONES:
        add_zone(board, name, layer, pts, clr, pri)

    # Ensure keepout survives (in case export/import dropped it)
    track_keepout_b(board, [(38.0, 86.0), (95.0, 86.0), (95.0, 92.0), (38.0, 92.0)])

    # Island A insurance: P3-1 north stitch into top gutter
    p3_1 = find_pad(board, "P3", "1")
    if p3_1 is not None:
        px, py = ToMM(p3_1.GetPosition().x), ToMM(p3_1.GetPosition().y)
        add_track(board, "GND", F_Cu, px, py, px, 6.0, 0.45)
        add_via(board, "GND", px, 6.0)
        print(f"stitch P3-1 -> ({px:.2f},6.0)")

    bridge_s3_5v_jp1(board)

    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(BOARD_PATH), board)
    print("OK post_fix_power")
    return 0


def bridge_s3_5v_jp1(board) -> None:
    """Connect JP1-2 to P2/TP5 S3_5V tree on B.Cu via grid BFS (left/bottom gutter)."""
    jp1 = find_pad(board, "JP1", "2")
    if jp1 is None:
        return
    jx, jy = ToMM(jp1.GetPosition().x), ToMM(jp1.GetPosition().y)

    occ: set[tuple[int, int]] = set()
    # ENC keepout strip (also scrubbed) — do not re-fence GND
    for x in range(38, 96):
        for y in range(86, 93):
            occ.add((x, y))
    for fp in board.GetFootprints():
        for p in fp.Pads():
            x, y = ToMM(p.GetPosition().x), ToMM(p.GetPosition().y)
            # Block NPTH mounting holes + foreign pads (keep clear of MH_*)
            is_npth = False
            try:
                is_npth = p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH
            except Exception:
                is_npth = fp.GetReference().startswith("MH") or fp.GetReference().startswith("H")
            if p.GetNetname() == "S3_5V" and not is_npth:
                continue
            rad = 2 if (fp.GetReference() == "JP1" or is_npth) else 1
            for dx in range(-rad, rad + 1):
                for dy in range(-rad, rad + 1):
                    occ.add((int(round(x)) + dx, int(round(y)) + dy))
    for t in board.GetTracks():
        if t.Type() == pcbnew.PCB_VIA_T:
            if t.GetNetname() == "S3_5V":
                continue
            x, y = ToMM(t.GetPosition().x), ToMM(t.GetPosition().y)
            occ.add((int(round(x)), int(round(y))))
            continue
        if t.GetLayer() != B_Cu or t.GetNetname() == "S3_5V":
            continue
        x1, y1 = ToMM(t.GetStart().x), ToMM(t.GetStart().y)
        x2, y2 = ToMM(t.GetEnd().x), ToMM(t.GetEnd().y)
        n = max(1, int(max(abs(x2 - x1), abs(y2 - y1))))
        for i in range(n + 1):
            x = x1 + (x2 - x1) * i / n
            y = y1 + (y2 - y1) * i / n
            occ.add((int(round(x)), int(round(y))))

    targets: set[tuple[int, int]] = set()
    for t in board.GetTracks():
        if t.GetNetname() != "S3_5V":
            continue
        pts = [t.GetPosition()] if t.Type() == pcbnew.PCB_VIA_T else [t.GetStart(), t.GetEnd()]
        for pt in pts:
            x, y = ToMM(pt.x), ToMM(pt.y)
            if x > 40:
                targets.add((int(round(x)), int(round(y))))
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetNetname() != "S3_5V":
                continue
            x, y = ToMM(p.GetPosition().x), ToMM(p.GetPosition().y)
            if x > 40:
                targets.add((int(round(x)), int(round(y))))

    def free(x: float, y: float) -> bool:
        return (int(round(x)), int(round(y))) not in occ

    q = deque([(jx, jy, [(jx, jy)])])
    seen = {(int(jx), int(jy))}
    path = None
    for _ in range(250000):
        if not q:
            break
        x, y, p = q.popleft()
        if (int(round(x)), int(round(y))) in targets and len(p) > 1:
            path = p
            break
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if not (2 <= nx <= 168 and 2 <= ny <= 118):
                continue
            key = (int(nx), int(ny))
            if key in seen or not free(nx, ny):
                continue
            seen.add(key)
            q.append((nx, ny, p + [(nx, ny)]))

    if not path:
        print("WARN: no B.Cu path for S3_5V JP1 bridge")
        return

    corners = [path[0]]
    for i in range(1, len(path) - 1):
        x0, y0 = corners[-1]
        x1, y1 = path[i]
        x2, y2 = path[i + 1]
        if (round(x1 - x0, 3), round(y1 - y0, 3)) != (round(x2 - x1, 3), round(y2 - y1, 3)):
            corners.append((x1, y1))
    corners.append(path[-1])
    for (x1, y1), (x2, y2) in zip(corners, corners[1:]):
        add_track(board, "S3_5V", B_Cu, x1, y1, x2, y2, 0.35)
    print(f"bridge S3_5V JP1 B.Cu corners={len(corners)} end={corners[-1]}")


if __name__ == "__main__":
    sys.exit(main())
