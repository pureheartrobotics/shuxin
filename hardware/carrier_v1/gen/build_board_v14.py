#!/usr/bin/env python3
"""Carrier V1.5 board builder — V1.4 re-review fab blockers (KiCad 10 pcbnew)."""
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
        f = pcbnew.FootprintLoad(path, name)
    if f is None:
        raise RuntimeError(f"Footprint not found: {lib_rel} / {name}")
    return f


def place(board, f, ref, x, y, value=""):
    f.SetReference(ref)
    if value:
        f.SetValue(value)
    f.SetPosition(mm(x, y))
    try:
        f.Value().SetVisible(False)
    except Exception:
        pass
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


def zone(board, name, layer, pts, clearance=0.4):
    z = pcbnew.ZONE(board)
    code = net(board, name)
    z.SetNetCode(code)
    # KiCad 10: also bind NETINFO so GetNetname() survives save/fill
    ni = board.GetNetInfo().GetNetItem(name)
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
    # Re-assert after Add (some builds clear net on insert)
    z.SetNetCode(code)
    if ni and hasattr(z, "SetNet"):
        z.SetNet(ni)
    return z


def track_keepout_b(board, pts):
    """B.Cu keepout: block signal tracks (allow vias + zone fills) so GND pour stays whole."""
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
    return z


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


def setup_rules(board) -> None:
    ds = board.GetDesignSettings()
    # Match FreeRouting defaults (documented in FAB.md as 0.6 / 0.3)
    try:
        ds.m_ViasMinSize = FromMM(0.6)
        ds.m_ViasMinDrill = FromMM(0.3)
        ds.m_ViasDefaultSize = FromMM(0.6)
        ds.m_ViasDefaultDrill = FromMM(0.3)
    except Exception:
        pass

    ns = ds.m_NetSettings
    power = pcbnew.NETCLASS("Power")
    power.SetTrackWidth(FromMM(1.6))
    power.SetClearance(FromMM(0.45))
    power.SetViaDiameter(FromMM(1.0))
    power.SetViaDrill(FromMM(0.5))
    ns.SetNetclass("Power", power)
    for pat in ("VBAT*", "VM*", "V_SERVO"):
        ns.SetNetclassPatternAssignment(pat, "Power")

    logic = pcbnew.NETCLASS("LogicPower")
    logic.SetTrackWidth(FromMM(0.5))
    logic.SetClearance(FromMM(0.25))
    logic.SetViaDiameter(FromMM(0.8))
    logic.SetViaDrill(FromMM(0.4))
    ns.SetNetclass("LogicPower", logic)
    for pat in ("+3V3", "+5V_LOGIC", "S3_5V"):
        ns.SetNetclassPatternAssignment(pat, "LogicPower")

    gnd = pcbnew.NETCLASS("GND")
    gnd.SetTrackWidth(FromMM(0.5))
    gnd.SetClearance(FromMM(0.25))
    gnd.SetViaDiameter(FromMM(0.8))
    gnd.SetViaDrill(FromMM(0.4))
    ns.SetNetclass("GND", gnd)
    ns.SetNetclassPatternAssignment("GND", "GND")
    ns.RecomputeEffectiveNetclasses()


def mkds(board, ref, x, y, value, n1, n2):
    f = fp(
        "TerminalBlock_Phoenix.pretty",
        "TerminalBlock_Phoenix_MKDS-1,5-2_1x02_P5.00mm_Horizontal",
    )
    place(board, f, ref, x, y, value)
    bind(board, f, {"1": n1, "2": n2})
    return f


def main() -> int:
    board = pcbnew.NewBoard(str(BOARD_PATH))
    setup_rules(board)

    edge = pcbnew.PCB_SHAPE(board)
    edge.SetShape(pcbnew.SHAPE_T_RECT)
    edge.SetLayer(Edge_Cuts)
    edge.SetStart(mm(0, 0))
    edge.SetEnd(mm(W, H))
    edge.SetWidth(FromMM(0.1))
    board.Add(edge)

    tb = board.GetTitleBlock()
    tb.SetTitle("shuxin Carrier V1.5")
    tb.SetRevision("F")
    tb.SetDate("2026-11-12")
    tb.SetCompany("pureheartrobotics")
    silk(board, "shuxin CARRIER V1.5  170x120mm  JST XH 2.50mm  Rev F", 6, 114, 1.15)
    silk(board, "JP1: +5V_LOGIC->S3_5V (pull when USB-flash). BAT only on XT60 JBAT.", 6, 117, 0.85)

    HDR = "Connector_PinHeader_2.54mm.pretty"
    JST = "Connector_JST.pretty"

    # --- Power path: XT60 -> D1(20A) -> F1 -> SW1 -> VM ---
    jbat = fp("Connector_AMASS.pretty", "AMASS_XT60PW-M_1x02_P7.20mm_Horizontal")
    place(board, jbat, "JBAT", 14, 12, "XT60PW-M")
    bind(board, jbat, {"1": "VBAT", "2": "GND"})
    silk(board, "BAT ONLY", 8, 6, 0.9)

    # DO-201AD 20A Schottky (SR20100 / MBR20100). Pad1=K, Pad2=A.
    # Place left of P1 (P1 @ x=58) — body spans +12.7 mm from origin.
    d1 = fp("Diode_THT.pretty", "D_DO-201AD_P12.70mm_Horizontal")
    place(board, d1, "D1", 28, 12, "SR20100")
    bind(board, d1, {"2": "VBAT", "1": "VBAT_F"})
    silk(board, "A<-BAT  K->FUSE", 24, 7, 0.75)

    mkds(board, "F1", 14, 30, "FUSE-12A", "VBAT_F", "VM_PRE")
    silk(board, "FUSE", 8, 24, 0.85)
    mkds(board, "SW1", 14, 44, "SW-15A", "VM_PRE", "VM")
    silk(board, "SW", 8, 38, 0.85)
    mkds(board, "JVM", 14, 58, "TO-D24A", "VM", "GND")
    silk(board, "D24A-VIN", 8, 52, 0.85)
    mkds(board, "JK11", 14, 72, "TO-K11C", "VM", "GND")
    silk(board, "K11C-12V", 8, 66, 0.85)

    ubuck = fp(HDR, "PinHeader_1x04_P2.54mm_Vertical")
    place(board, ubuck, "UBUCK", 14, 86, "BUCK-8.4V")
    bind(board, ubuck, {"1": "VM", "2": "GND", "3": "V_SERVO", "4": "GND"})

    jp1 = fp(HDR, "PinHeader_1x02_P2.54mm_Vertical")
    place(board, jp1, "JP1", 14, 100, "5V-EN")
    bind(board, jp1, {"1": "+5V_LOGIC", "2": "S3_5V"})

    # Bulk caps — clear of connectors
    cin = fp("Capacitor_THT.pretty", "CP_Radial_D8.0mm_P3.50mm")
    place(board, cin, "C_IN", 30, 58, "100u")
    bind(board, cin, {"1": "VM", "2": "GND"})

    # 3V3 decoupling near K11C (THT so GND ties into B.Cu pour without stitch vias)
    c33 = fp("Capacitor_THT.pretty", "C_Disc_D5.0mm_W2.5mm_P2.50mm")
    place(board, c33, "C_3V3", 56, 54, "10u")
    bind(board, c33, {"1": "+3V3", "2": "GND"})

    # Servo caps — clear of XH seats (x=145) and corner hole H2 (165,5)
    for ref, y in (("C_SERVO1", 16), ("C_SERVO2", 32)):
        c = fp("Capacitor_THT.pretty", "CP_Radial_D8.0mm_P3.50mm")
        place(board, c, ref, 160, y, "470u")
        bind(board, c, {"1": "V_SERVO", "2": "GND"})

    # P1 K11C — DEBUG 25/27 NC (keep clear of D1 @ x=28..40.7)
    p1 = fp(HDR, "PinHeader_2x15_P2.54mm_Vertical")
    place(board, p1, "P1", 58, 12, "K11C")
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

    # DevKit — P2-1/2 intentionally NC (no dual 3V3 with DevKit LDO)
    p2x, p2y = 96.0, 10.0
    p3x = p2x + DEVKIT_ROW
    p2 = fp(HDR, "PinHeader_1x22_P2.54mm_Vertical")
    p3 = fp(HDR, "PinHeader_1x22_P2.54mm_Vertical")
    place(board, p2, "P2", p2x, p2y, "S3-J1")
    place(board, p3, "P3", p3x, p2y, "S3-J3")
    silk(board, f"row={DEVKIT_ROW}mm", p2x, 5, 0.9)
    silk(board, "P2-1/2 NC (no 3V3 dual-source)", p2x, 68, 0.75)

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
            # 1,2 intentionally omitted — DevKit LDO must not parallel K11C 3V3
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

    for ref, nname, y in (("R14", "I2C3_SCL", 58), ("R15", "I2C3_SDA", 62)):
        r = fp("Resistor_SMD.pretty", "R_0603_1608Metric")
        place(board, r, ref, 62, y, "4K7")
        bind(board, r, {"1": nname, "2": "+3V3"})

    def xh(n):
        return fp(JST, f"JST_XH_B{n}B-XH-A_1x{n:02d}_P2.50mm_Vertical")

    ju = xh(4)
    place(board, ju, "J_UART", 58, 72, "UART")
    bind(board, ju, {"1": "UART_K11C_TX", "2": "UART_K11C_RX", "3": "GND", "4": ""})
    silk(board, "UART (or P1, not both)", 52, 68, 0.75)

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
        place(board, j, ref, 145, y, label)
        bind(board, j, {"1": sig, "2": "V_SERVO", "3": "GND"})
        silk(board, label, 145, y - 4, 0.9)

    jtof = xh(4)
    place(board, jtof, "J_TOF", 145, 48, "TOF")
    bind(board, jtof, {"1": "+3V3", "2": "GND", "3": "I2C3_SCL", "4": "I2C3_SDA"})
    silk(board, "TOF", 145, 44, 0.9)

    # Test points — PTH pins for power/GND so they hit B.Cu pour; pad OK for signals
    for i, (nname, x, y, pth) in enumerate(
        [
            ("VM", 38, 40, True),
            ("V_SERVO", 38, 46, True),
            ("+3V3", 38, 64, True),
            ("+5V_LOGIC", 38, 70, True),
            ("S3_5V", 70, 58, True),
            ("GND", 38, 100, True),
            ("UART_K11C_TX", 72, 64, False),
        ],
        1,
    ):
        if pth:
            tp = fp(HDR, "PinHeader_1x01_P2.54mm_Vertical")
        else:
            try:
                tp = fp("TestPoint.pretty", "TestPoint_Pad_D1.5mm")
            except RuntimeError:
                tp = fp(HDR, "PinHeader_1x01_P2.54mm_Vertical")
        place(board, tp, f"TP{i}", x, y, nname)
        bind(board, tp, {"1": nname})

    for i, (x, y) in enumerate([(4, 4), (W - 4, 4), (4, H - 4), (W - 4, H - 4)], 1):
        npth(board, f"H{i}", x, y)
    for i, (x, y) in enumerate([(48, 6), (150, 6), (48, 78), (150, 78)], 1):
        npth(board, f"MH_K11C{i}", x, y, "K11C")
    for i, (x, y) in enumerate([(40, 114), (130, 114)], 1):
        npth(board, f"MH_D24A{i}", x, y, "D24A")

    # Zones: non-overlapping F.Cu power islands + full B.Cu GND
    # NO F.Cu GND island near VBAT (that caused zones_intersect + short risk)
    zone(board, "GND", B_Cu, [(1.5, 1.5), (W - 1.5, 1.5), (W - 1.5, H - 1.5), (1.5, H - 1.5)], 0.35)
    zone(board, "VBAT", F_Cu, [(4, 4), (26, 4), (26, 20), (4, 20)], 0.45)
    zone(board, "VBAT_F", F_Cu, [(28, 4), (48, 4), (48, 20), (28, 20)], 0.45)  # under D1 cathode
    zone(board, "VM", F_Cu, [(4, 36), (28, 36), (28, 104), (4, 104)], 0.45)
    zone(board, "V_SERVO", F_Cu, [(154, 8), (168, 8), (168, 42), (154, 42)], 0.45)
    # V1.5 P0: forbid B.Cu signal tracks under ENC row (was +3V3 fencing GND pads)
    track_keepout_b(board, [(38.0, 86.0), (95.0, 86.0), (95.0, 92.0), (38.0, 92.0)])

    track(board, 14, 12, 24, 12, "VBAT", 3.0)
    track(board, 40, 12, 44, 12, "VBAT_F", 2.5)
    track(board, 14, 30, 14, 40, "VM_PRE", 2.5)
    track(board, 14, 44, 20, 44, "VM", 2.5)

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
