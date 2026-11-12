#!/usr/bin/env python3
"""Grid A* router for carrier_v1 using KiCad pcbnew."""
from __future__ import annotations

import heapq
import sys
from collections import defaultdict
from pathlib import Path

import pcbnew

BOARD_PATH = Path(__file__).resolve().parents[1] / "carrier_v1.kicad_pcb"
GRID = 0.5  # mm
W, H = 140.0, 100.0
MARGIN = 1.5


def mm(v: float) -> int:
    return int(pcbnew.FromMM(float(v)))


def to_mm(v: int) -> float:
    return float(pcbnew.ToMM(v))


def pad_xy(pad):
    p = pad.GetPosition()
    return to_mm(p.x), to_mm(p.y)


class Grid:
    def __init__(self):
        self.nx = int((W - 2 * MARGIN) / GRID)
        self.ny = int((H - 2 * MARGIN) / GRID)
        # blocked[layer][ix+iy*nx] = netcode owning or -1 free, -2 blocked solid
        self.blocked = {
            pcbnew.F_Cu: [0] * (self.nx * self.ny),
            pcbnew.B_Cu: [0] * (self.nx * self.ny),
        }

    def xy_to_ij(self, x: float, y: float) -> tuple[int, int]:
        ix = int((x - MARGIN) / GRID)
        iy = int((y - MARGIN) / GRID)
        ix = max(0, min(self.nx - 1, ix))
        iy = max(0, min(self.ny - 1, iy))
        return ix, iy

    def ij_to_xy(self, ix: int, iy: int) -> tuple[float, float]:
        return MARGIN + (ix + 0.5) * GRID, MARGIN + (iy + 0.5) * GRID

    def idx(self, ix: int, iy: int) -> int:
        return ix + iy * self.nx

    def mark_disk(self, layer: int, x: float, y: float, r: float, code: int) -> None:
        ix0, iy0 = self.xy_to_ij(x, y)
        rad = int(r / GRID) + 1
        for dy in range(-rad, rad + 1):
            for dx in range(-rad, rad + 1):
                if dx * dx + dy * dy > rad * rad:
                    continue
                ix, iy = ix0 + dx, iy0 + dy
                if 0 <= ix < self.nx and 0 <= iy < self.ny:
                    i = self.idx(ix, iy)
                    if self.blocked[layer][i] == 0:
                        self.blocked[layer][i] = code if code else -2

    def passable(self, layer: int, ix: int, iy: int, netcode: int) -> bool:
        if not (0 <= ix < self.nx and 0 <= iy < self.ny):
            return False
        v = self.blocked[layer][self.idx(ix, iy)]
        return v == 0 or v == netcode

    def occupy_path(self, layer: int, cells: list[tuple[int, int]], netcode: int, width_cells: int = 0) -> None:
        for ix, iy in cells:
            for dy in range(-width_cells, width_cells + 1):
                for dx in range(-width_cells, width_cells + 1):
                    x, y = ix + dx, iy + dy
                    if 0 <= x < self.nx and 0 <= y < self.ny:
                        self.blocked[layer][self.idx(x, y)] = netcode


def astar(grid: Grid, layer: int, start: tuple[float, float], goal: tuple[float, float], netcode: int):
    s = grid.xy_to_ij(*start)
    g = grid.xy_to_ij(*goal)
    if not grid.passable(layer, *s, netcode) and grid.blocked[layer][grid.idx(*s)] not in (0, netcode):
        # force allow start
        grid.blocked[layer][grid.idx(*s)] = netcode
    if not grid.passable(layer, *g, netcode) and grid.blocked[layer][grid.idx(*g)] not in (0, netcode):
        grid.blocked[layer][grid.idx(*g)] = netcode

    def h(a, b):
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    openh = [(h(s, g), 0, s)]
    came = {}
    gscore = {s: 0}
    closed = set()
    while openh:
        _, cost, cur = heapq.heappop(openh)
        if cur in closed:
            continue
        if cur == g:
            path = [cur]
            while cur in came:
                cur = came[cur]
                path.append(cur)
            path.reverse()
            return path
        closed.add(cur)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (cur[0] + dx, cur[1] + dy)
            if not grid.passable(layer, nxt[0], nxt[1], netcode):
                continue
            ng = cost + 1
            if ng < gscore.get(nxt, 1e18):
                gscore[nxt] = ng
                came[nxt] = cur
                heapq.heappush(openh, (ng + h(nxt, g), ng, nxt))
    return None


def simplify(cells: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if len(cells) <= 2:
        return cells
    out = [cells[0]]
    for i in range(1, len(cells) - 1):
        ax, ay = out[-1]
        bx, by = cells[i]
        cx, cy = cells[i + 1]
        if (bx - ax) * (cy - by) == (by - ay) * (cx - bx):
            continue  # colinear
        out.append(cells[i])
    out.append(cells[-1])
    return out


def main() -> int:
    # start from clean placement
    board = pcbnew.LoadBoard(str(BOARD_PATH))
    for t in list(board.GetTracks()):
        board.Remove(t)

    grid = Grid()
    pads_by_net: dict[str, list[dict]] = defaultdict(list)
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        for pad in fp.Pads():
            net = pad.GetNetname() or ""
            if not net or net == "NC_DEBUG":
                continue
            x, y = pad_xy(pad)
            code = pad.GetNetCode()
            size = to_mm(pad.GetSizeX()) / 2.0
            # Block slightly less than full clearance so A* can skirt headers;
            # DRC still enforces final spacing after route.
            for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
                grid.mark_disk(layer, x, y, max(0.55, size * 0.85), code)
            pads_by_net[net].append({"ref": ref, "num": pad.GetNumber(), "x": x, "y": y, "code": code})

    order = [
        "VBAT", "VBAT_F", "VM", "V_SERVO", "+5V_LOGIC", "+3V3",
        "UART_K11C_TX", "UART_K11C_RX", "I2C3_SCL", "I2C3_SDA",
        "SERVO_PAN", "SERVO_TILT",
        "ENC_A_A", "ENC_A_B", "ENC_B_A", "ENC_B_B",
        "ENC_C_A", "ENC_C_B", "ENC_D_A", "ENC_D_B",
        "STBY", "PWMA", "AIN1", "AIN2", "PWMB", "BIN1", "BIN2",
        "PWMC", "CIN1", "CIN2", "PWMD", "DIN1", "DIN2",
    ]

    def uniq(ps):
        o = []
        for p in ps:
            if not any(abs(p["x"] - q["x"]) < 0.2 and abs(p["y"] - q["y"]) < 0.2 for q in o):
                o.append(p)
        return o

    ok = fail = 0
    for name in [n for n in order if n in pads_by_net]:
        pads = uniq(pads_by_net[name])
        if len(pads) < 2:
            continue
        pads = sorted(pads, key=lambda p: (p["x"], p["y"]))
        width = 0.9 if name in ("VBAT", "VBAT_F", "VM") else (0.5 if name in ("V_SERVO", "+5V_LOGIC", "+3V3") else 0.25)
        layer = pcbnew.B_Cu if name in {
            "STBY", "PWMA", "AIN1", "AIN2", "PWMB", "BIN1", "BIN2",
            "PWMC", "CIN1", "CIN2", "PWMD", "DIN1", "DIN2",
        } else pcbnew.F_Cu
        wcells = 1 if width >= 0.6 else 0
        remaining = pads[1:]
        cur = pads[0]
        code = cur["code"]
        # allow this net's pads
        for p in pads:
            for lay in (pcbnew.F_Cu, pcbnew.B_Cu):
                ix, iy = grid.xy_to_ij(p["x"], p["y"])
                grid.blocked[lay][grid.idx(ix, iy)] = code

        def escape(p):
            # Clear a short horizontal tunnel into free air for header pads
            ix, iy = grid.xy_to_ij(p["x"], p["y"])
            direction = -1
            if p["ref"] in ("P3", "P6", "P7"):
                direction = 1
            if p["ref"] in ("P4", "P5"):
                direction = 0  # vertical escape up
            for step in range(1, 8):
                if direction == 0:
                    jx, jy = ix, iy - step
                else:
                    jx, jy = ix + direction * step, iy
                if 0 <= jx < grid.nx and 0 <= jy < grid.ny:
                    for lay in (pcbnew.F_Cu, pcbnew.B_Cu):
                        grid.blocked[lay][grid.idx(jx, jy)] = code

        for p in pads:
            escape(p)

        while remaining:
            remaining.sort(key=lambda p: (p["x"] - cur["x"]) ** 2 + (p["y"] - cur["y"]) ** 2)
            nxt = remaining.pop(0)
            path = astar(grid, layer, (cur["x"], cur["y"]), (nxt["x"], nxt["y"]), code)
            if path is None:
                other = pcbnew.F_Cu if layer == pcbnew.B_Cu else pcbnew.B_Cu
                path = astar(grid, other, (cur["x"], cur["y"]), (nxt["x"], nxt["y"]), code)
                use_layer = other
            else:
                use_layer = layer
            if path is None:
                fail += 1
                print(f"FAIL {name} {cur['ref']}.{cur['num']}->{nxt['ref']}.{nxt['num']}")
                continue
            cells = simplify(path)
            grid.occupy_path(use_layer, path, code, wcells)
            # emit tracks between simplified corners (in mm)
            pts = [grid.ij_to_xy(ix, iy) for ix, iy in cells]
            # snap ends to real pad centers
            pts[0] = (cur["x"], cur["y"])
            pts[-1] = (nxt["x"], nxt["y"])
            for i in range(len(pts) - 1):
                x1, y1 = pts[i]
                x2, y2 = pts[i + 1]
                t = pcbnew.PCB_TRACK(board)
                t.SetStart(pcbnew.VECTOR2I(mm(x1), mm(y1)))
                t.SetEnd(pcbnew.VECTOR2I(mm(x2), mm(y2)))
                t.SetWidth(mm(width))
                t.SetLayer(use_layer)
                t.SetNetCode(code)
                board.Add(t)
            ok += 1
            cur = nxt

    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    pcbnew.SaveBoard(str(BOARD_PATH), board)
    print(f"ok={ok} fail={fail} saved={BOARD_PATH}")
    return 0 if fail == 0 else 1


def CLEAR_PAD():
    return 0.35


if __name__ == "__main__":
    sys.exit(main())
