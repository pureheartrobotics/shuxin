#!/usr/bin/env python3
"""Carrier V1.4 board builder — fixes review P0/P1 (KiCad 10 pcbnew)."""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

import pcbnew
from pcbnew import (
    VECTOR2I,
    FromMM,
    F_Cu,
    B_Cu,
    F_SilkS,
    Edge_Cuts,
    PAD_ATTRIB_NPTH,
    ZONE_CONNECTION_FULL,
)

ROOT = Path(__file__).resolve().parents[1]
BOARD_PATH = ROOT / "carrier_v1.kicad_pcb"
KFP = Path(r"C:\Users\syk\AppData\Local\Programs\KiCad\10.0\share\kicad\footprints")
W, H = 170.0, 120.0
DEVKIT_ROW = 22.86


def mm(x, y):
    return VECTOR2I(FromMM(x), FromMM(y))


def net(board, name: str) -> int:
    info = board.GetNetInfo()
    existing = info.GetNetItem(name)
    if existing:
        return existing.GetNetCode()
    item = pcbnew.NETINFO_ITEM(board, name)
    board.Add(item)
    return item.GetNetCode()


_IO = None


def fp(lib_rel: str, name: str):
    global _IO
    path = str(KFP / lib_rel)
    if _IO is None:
        _IO = pcbnew.PCB_IO_MGR.FindPlugin(pcbnew.PCB_IO_MGR.KICAD_SEXP)
    f = _IO.FootprintLoad(path, name)
    if f is None:
        # fallback
        f = pcbnew.FootprintLoad(path, name)
    if f is None:
        raise RuntimeError(f"Footprint not found: {lib_rel} / {name}")
    return f


def place(board, f, ref, x, y, value=""):
    f.SetReference(ref)
    if value:
        f.SetValue(value)
    f.SetPosition(mm(x, y))
    board.Add(f)
    return f


def bind(board, f, mapping: dict):
    for pad in f.Pads():
        n = pad.GetNumber()
        if n in mapping and mapping[n]:
            pad.SetNetCode(net(board, mapping[n]))
        else:
            pad.SetNetCode(0)


def silk(board, text, x, y, size=1.0):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(text)
    t.SetPosition(mm(x, y))
    t.SetLayer(F_SilkS)
    t.SetTextSize(VECTOR2I(FromMM(size), FromMM(size)))
    t.SetTextThickness(FromMM(0.12))
    board.Add(t)


def zone(board, name, layer, pts, clearance=0.35):
    z = pcbnew.ZONE(board)
    z.SetNetCode(net(board, name))
    z.SetLayer(layer)
    z.SetLocalClearance(FromMM(clearance))
    z.SetMinThickness(FromMM(0.25))
    z.SetPadConnection(ZONE_CONNECTION_FULL)
    poly = z.Outline()
    poly.RemoveAllContours()
    poly.NewOutline()
    for x, y in pts:
        poly.Append(FromMM(x), FromMM(y))
    board.Add(z)


def track(board, x1, y1, x2, y2, name, w, layer=F_Cu):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(mm(x1, y1))
    t.SetEnd(mm(x2, y2))
    t.SetWidth(FromMM(w))
    t.SetLayer(layer)
    t.SetNetCode(net(board, name))
    board.Add(t)


def npth(board, ref, x, y, value="M3"):
    try:
        h = fp("MountingHole.pretty", "MountingHole_3.2mm_M3")
    except RuntimeError:
        h = fp("MountingHole.pretty", "MountingHole_3.2mm_M3_Pad")
    place(board, h, ref, x, y, value)
    for p in h.Pads():
        p.SetAttribute(PAD_ATTRIB_NPTH)
        p.SetNetCode(0)


def setup_netclasses(board) -> None:
    """Power nets route thick from the start (avoids post-widen shorts)."""
    ns = board.GetDesignSettings().m_NetSettings
    power = pcbnew.NETCLASS("Power")
    power.SetTrackWidth(FromMM(1.6))
    power.SetClearance(FromMM(0.45))
    power.SetViaDiameter(FromMM(1.0))
    power.SetViaDrill(FromMM(0.5))
    ns.SetNetclass("Power", power)
    for pat in ("VBAT*", "VM*", "V_SERVO"):
        ns.SetNetclassPatternAssignment(pat, "Power")
    gnd = pcbnew.NETCLASS("GND")
    gnd.SetTrackWidth(FromMM(0.5))
    gnd.SetClearance(FromMM(0.25))
    gnd.SetViaDiameter(FromMM(0.8))
    gnd.SetViaDrill(FromMM(0.4))
    ns.SetNetclass("GND", gnd)
    ns.SetNetclassPatternAssignment("GND", "GND")
    ns.RecomputeEffectiveNetclasses()


def main() -> int:
    board = pcbnew.NewBoard(str(BOARD_PATH))
    setup_netclasses(board)
    # Edge
    edge = pcbnew.PCB_SHAPE(board)
    edge.SetShape(pcbnew.SHAPE_T_RECT)
    edge.SetLayer(Edge_Cuts)
    edge.SetStart(mm(0, 0))
    edge.SetEnd(mm(W, H))
    edge.SetWidth(FromMM(0.1))
    board.Add(edge)

    tb = board.GetTitleBlock()
    tb.SetTitle("shuxin Carrier V1.4")
    tb.SetRevision("E")
    tb.SetDate("2026-11-12")
    tb.SetCompany("pureheartrobotics")
    silk(board, "shuxin CARRIER V1.4  170x120mm  JST XH 2.50mm", 6, 114, 1.2)
    silk(board, "JP1 bridges +5V_LOGIC to S3_5V (P2-21); remove when USB-flashing", 6, 117, 0.95)

    HDR = "Connector_PinHeader_2.54mm.pretty"
    JST = "Connector_JST.pretty"

    def power2(ref, x, y, value, n1, n2):
        # Prefer Phoenix 5.08 terminal; fallback 2.54 header (documented in BOM)
        try:
            f = fp(
                "TerminalBlock_Phoenix.pretty",
                "TerminalBlock_Phoenix_MKDS-1,5-2_1x02_P5.00mm_Horizontal",
            )
        except RuntimeError:
            f = fp(HDR, "PinHeader_1x02_P2.54mm_Vertical")
        place(board, f, ref, x, y, value)
        bind(board, f, {"1": n1, "2": n2})
        return f

    # Power path (left column, clear of P1): JBAT -> D1 -> F1 -> SW1 -> VM
    # KiCad D_SMC: pad1=K (cathode), pad2=A (anode). Series reverse-polarity: BAT+→A→K→fuse.
    power2("JBAT", 12, 12, "BAT/XT60-wire", "VBAT", "GND")

    try:
        d1 = fp("Diode_SMD.pretty", "D_SMC")
    except RuntimeError:
        d1 = fp("Diode_SMD.pretty", "D_SOD-123")
    place(board, d1, "D1", 26, 12, "SS54")
    bind(board, d1, {"2": "VBAT", "1": "VBAT_F"})

    power2("F1", 12, 26, "FUSE-wires", "VBAT_F", "VM_PRE")
    power2("SW1", 12, 40, "SW-wires", "VM_PRE", "VM")
    power2("JVM", 12, 54, "D24A-VIN", "VM", "GND")
    power2("JK11", 12, 68, "K11C-12V", "VM", "GND")

    ubuck = fp(HDR, "PinHeader_1x04_P2.54mm_Vertical")
    place(board, ubuck, "UBUCK", 12, 82, "BUCK")
    bind(board, ubuck, {"1": "VM", "2": "GND", "3": "V_SERVO", "4": "GND"})

    jp1 = fp(HDR, "PinHeader_1x02_P2.54mm_Vertical")
    place(board, jp1, "JP1", 12, 96, "5V-EN")
    bind(board, jp1, {"1": "+5V_LOGIC", "2": "S3_5V"})

    # Caps
    try:
        cin = fp("Capacitor_THT.pretty", "CP_Radial_D8.0mm_P3.50mm")
    except RuntimeError:
        cin = fp("Capacitor_SMD.pretty", "C_1206_3216Metric")
    place(board, cin, "C_IN", 28, 54, "100u")
    bind(board, cin, {"1": "VM", "2": "GND"})
    for ref, y in (("C_SERVO1", 16), ("C_SERVO2", 30)):
        try:
            c = fp("Capacitor_THT.pretty", "CP_Radial_D8.0mm_P3.50mm")
        except RuntimeError:
            c = fp("Capacitor_SMD.pretty", "C_1206_3216Metric")
        place(board, c, ref, 158, y, "470u")
        bind(board, c, {"1": "V_SERVO", "2": "GND"})

    # P1 — no 5V to K11C, DEBUG NC; keep clear of left power column
    p1 = fp(HDR, "PinHeader_2x15_P2.54mm_Vertical")
    place(board, p1, "P1", 48, 12, "K11C")
    bind(
        board,
        p1,
        {
            "1": "+3V3",
            "3": "GND",
            "6": "GND",
            "13": "GND",
            "15": "UART_K11C_RX",
            "16": "I2C3_SCL",
            "17": "UART_K11C_TX",
            "18": "I2C3_SDA",
            "23": "GND",
            "29": "GND",
        },
    )

    # DevKit headers (row pitch 22.86 mm)
    p2x, p2y = 96.0, 10.0
    p3x = p2x + DEVKIT_ROW
    p2 = fp(HDR, "PinHeader_1x22_P2.54mm_Vertical")
    p3 = fp(HDR, "PinHeader_1x22_P2.54mm_Vertical")
    place(board, p2, "P2", p2x, p2y, "S3-J1")
    place(board, p3, "P3", p3x, p2y, "S3-J3")
    silk(board, f"row={DEVKIT_ROW}mm", p2x, 5, 0.9)

    # Control nets use *_J toward connectors; S3 pins use base names through resistors
    # Place 100R series between P2 column and CTRL area (left of P2)
    series = [
        ("R1", "STBY", p2x - 10, 12),
        ("R2", "PWMA", p2x - 10, 15.5),
        ("R3", "AIN1", p2x - 10, 19),
        ("R4", "AIN2", p2x - 10, 22.5),
        ("R5", "PWMB", p2x - 10, 26),
        ("R6", "BIN1", p2x - 10, 29.5),
        ("R7", "BIN2", p2x - 10, 33),
        ("R8", "PWMC", p2x - 10, 36.5),
        ("R9", "CIN1", p2x - 10, 40),
        ("R10", "CIN2", p2x - 10, 43.5),
        ("R11", "PWMD", p2x - 10, 47),
        ("R12", "DIN1", p3x + 8, 48),
        ("R13", "DIN2", p2x - 10, 50.5),
    ]
    for ref, nname, x, y in series:
        r = fp("Resistor_SMD.pretty", "R_1206_3216Metric")
        place(board, r, ref, x, y, "100R")
        bind(board, r, {"1": nname, "2": nname + "_J"})

    bind(
        board,
        p2,
        {
            "1": "+3V3",
            "2": "+3V3",
            "4": "PWMA",
            "5": "AIN1",
            "6": "AIN2",
            "7": "PWMB",
            "8": "BIN1",
            "9": "BIN2",
            "10": "UART_K11C_RX",
            "11": "UART_K11C_TX",
            "12": "STBY",
            "13": "ENC_A_B",
            "14": "ENC_A_A",
            "15": "PWMC",
            "16": "CIN1",
            "17": "CIN2",
            "18": "PWMD",
            "19": "ENC_B_B",
            "20": "DIN2",  # GPIO14
            "21": "S3_5V",
            "22": "GND",
        },
    )
    bind(
        board,
        p3,
        {
            "1": "GND",
            "4": "SERVO_PAN",
            "5": "SERVO_TILT",
            "6": "ENC_D_A",
            "7": "ENC_C_B",
            "9": "ENC_D_B",
            "10": "ENC_B_A",
            "17": "ENC_C_A",
            "18": "DIN1",  # GPIO21
            "21": "GND",
            "22": "GND",
        },
    )

    # I2C pullups near P1 I2C pins
    for ref, nname, y in (("R14", "I2C3_SCL", 58), ("R15", "I2C3_SDA", 62)):
        r = fp("Resistor_SMD.pretty", "R_0603_1608Metric")
        place(board, r, ref, 58, y, "4K7")
        bind(board, r, {"1": nname, "2": "+3V3"})

    def xh(n):
        return fp(JST, f"JST_XH_B{n}B-XH-A_1x{n:02d}_P2.50mm_Vertical")

    # UART 4P (keyed; not same family as servo 3P)
    ju = xh(4)
    place(board, ju, "J_UART", 58, 72, "UART")
    bind(board, ju, {"1": "UART_K11C_TX", "2": "UART_K11C_RX", "3": "GND", "4": ""})
    silk(board, "UART", 58, 68, 1.0)

    # CTRL AB vertical 8P; CD horizontal 8P (anti-mismatch)
    jab = xh(8)
    place(board, jab, "J_CTRL_AB", 48, 104, "CTRL-AB")
    bind(
        board,
        jab,
        {
            "1": "STBY_J",
            "2": "PWMA_J",
            "3": "AIN1_J",
            "4": "AIN2_J",
            "5": "PWMB_J",
            "6": "BIN1_J",
            "7": "BIN2_J",
            "8": "GND",
        },
    )
    silk(board, "CTRL-AB", 48, 99, 1.0)

    jcd = fp(JST, "JST_XH_S8B-XH-A_1x08_P2.50mm_Horizontal")
    place(board, jcd, "J_CTRL_CD", 92, 108, "CTRL-CD")
    bind(
        board,
        jcd,
        {
            "1": "PWMC_J",
            "2": "CIN1_J",
            "3": "CIN2_J",
            "4": "PWMD_J",
            "5": "DIN1_J",
            "6": "DIN2_J",
            "7": "+5V_LOGIC",
            "8": "GND",
        },
    )
    silk(board, "CTRL-CD", 92, 102, 1.0)

    for ref, x, a, b, label in [
        ("J_ENC_A", 36, "ENC_A_A", "ENC_A_B", "ENC-A"),
        ("J_ENC_B", 52, "ENC_B_A", "ENC_B_B", "ENC-B"),
        ("J_ENC_C", 68, "ENC_C_A", "ENC_C_B", "ENC-C"),
        ("J_ENC_D", 84, "ENC_D_A", "ENC_D_B", "ENC-D"),
    ]:
        j = xh(4)
        place(board, j, ref, x, 88, label)
        bind(board, j, {"1": a, "2": b, "3": "+3V3", "4": "GND"})
        silk(board, label, x, 84, 0.9)

    for ref, y, sig, label in [
        ("J_SERVO_PAN", 14, "SERVO_PAN", "SERVO-PAN"),
        ("J_SERVO_TILT", 28, "SERVO_TILT", "SERVO-TILT"),
    ]:
        j = xh(3)
        place(board, j, ref, 148, y, label)
        bind(board, j, {"1": sig, "2": "V_SERVO", "3": "GND"})
        silk(board, label, 148, y - 4, 0.9)

    jtof = xh(4)
    place(board, jtof, "J_TOF", 148, 48, "TOF")
    bind(board, jtof, {"1": "+3V3", "2": "GND", "3": "I2C3_SCL", "4": "I2C3_SDA"})
    silk(board, "TOF", 148, 44, 0.9)

    # Test points (right of power column, left of P1)
    for i, (nname, y) in enumerate(
        [("VM", 48), ("V_SERVO", 54), ("+3V3", 60), ("+5V_LOGIC", 66), ("S3_5V", 72), ("GND", 78), ("UART_K11C_TX", 84)],
        1,
    ):
        try:
            tp = fp("TestPoint.pretty", "TestPoint_Pad_D1.5mm")
        except RuntimeError:
            tp = fp(HDR, "PinHeader_1x01_P2.54mm_Vertical")
        place(board, tp, f"TP{i}", 34, y, nname)
        bind(board, tp, {"1": nname})

    # NPTH mounting holes (board corners + module anchors)
    for i, (x, y) in enumerate([(4, 4), (W - 4, 4), (4, H - 4), (W - 4, H - 4)], 1):
        npth(board, f"H{i}", x, y)
    for i, (x, y) in enumerate([(42, 6), (150, 6), (42, 72), (150, 72)], 1):
        npth(board, f"MH_K11C{i}", x, y, "K11C")
    for i, (x, y) in enumerate([(40, 114), (130, 114)], 1):
        npth(board, f"MH_D24A{i}", x, y, "D24A")

    # Zones + thick power spines (zones carry GND / VM / VBAT bulk)
    zone(board, "GND", B_Cu, [(1.5, 1.5), (W - 1.5, 1.5), (W - 1.5, H - 1.5), (1.5, H - 1.5)])
    zone(board, "GND", F_Cu, [(1.5, 1.5), (30, 1.5), (30, 28), (1.5, 28)])
    zone(board, "VM", F_Cu, [(1.5, 36), (30, 36), (30, 100), (1.5, 100)], 0.4)
    zone(board, "V_SERVO", F_Cu, [(140, 8), (168, 8), (168, 42), (140, 42)], 0.4)
    zone(board, "VBAT", F_Cu, [(6, 6), (34, 6), (34, 20), (6, 20)], 0.4)

    # Short stubs only — long power runs come from zones in post_fix_power.py
    track(board, 12, 12, 22, 12, "VBAT", 3.0)
    track(board, 12, 26, 12, 36, "VM_PRE", 2.5)
    track(board, 12, 40, 18, 40, "VM", 2.5)

    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(BOARD_PATH), board)
    print(f"OK {BOARD_PATH} fps={len(list(board.GetFootprints()))} nets={board.GetNetInfo().GetNetCount()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
