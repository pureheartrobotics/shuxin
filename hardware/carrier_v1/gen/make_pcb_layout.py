#!/usr/bin/env python3
"""Generate Carrier V1.1 KiCad PCB with spaced channels (KiCad 10)."""
from __future__ import annotations

import uuid
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "carrier_v1.kicad_pcb"
W, H = 140.0, 100.0
PITCH = 2.54


def uid() -> str:
    return str(uuid.uuid4())


NETS = [
    "",
    "GND",
    "VBAT",
    "VBAT_F",
    "VM",
    "V_SERVO",
    "+5V_LOGIC",
    "+3V3",
    "UART_K11C_TX",
    "UART_K11C_RX",
    "I2C3_SCL",
    "I2C3_SDA",
    "STBY",
    "PWMA",
    "AIN1",
    "AIN2",
    "PWMB",
    "BIN1",
    "BIN2",
    "PWMC",
    "CIN1",
    "CIN2",
    "PWMD",
    "DIN1",
    "DIN2",
    "ENC_A_A",
    "ENC_A_B",
    "ENC_B_A",
    "ENC_B_B",
    "ENC_C_A",
    "ENC_C_B",
    "ENC_D_A",
    "ENC_D_B",
    "SERVO_PAN",
    "SERVO_TILT",
    "NC_DEBUG",
]
NET_ID = {n: i for i, n in enumerate(NETS)}


def net_decl() -> str:
    return "\n".join(f'  (net {i} "{n}")' for i, n in enumerate(NETS))


def pad(num: str, x: float, y: float, net: str, size: float = 1.7, drill: float = 1.0) -> str:
    nid = NET_ID[net]
    shape = "rect" if str(num) == "1" else "circle"
    return (
        f'    (pad "{num}" thru_hole {shape} (at {x:.3f} {y:.3f}) (size {size} {size}) '
        f'(drill {drill}) (layers "*.Cu" "*.Mask") (net {nid} "{net}") '
        f'(solder_mask_margin 0.05) (uuid "{uid()}"))'
    )


def ref_text(ref: str) -> str:
    return (
        f'    (property "Reference" "{ref}" (at 0 -2.8 0) (layer "F.SilkS") (uuid "{uid()}")\n'
        f'      (effects (font (size 1.0 1.0) (thickness 0.15)))\n'
        f'    )\n'
        f'    (property "Value" "{ref}" (at 0 2.0 0) (layer "F.Fab") (uuid "{uid()}")\n'
        f'      (effects (font (size 0.8 0.8) (thickness 0.1)))\n'
        f'    )\n'
        f'    (property "Footprint" "" (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "{uid()}")\n'
        f'      (effects (font (size 1.27 1.27)))\n'
        f'    )\n'
        f'    (property "Datasheet" "" (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "{uid()}")\n'
        f'      (effects (font (size 1.27 1.27)))\n'
        f'    )\n'
        f'    (property "Description" "" (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "{uid()}")\n'
        f'      (effects (font (size 1.27 1.27)))\n'
        f'    )'
    )


def fp_header_v(ref: str, at: tuple[float, float], pins: list[tuple[str, str]]) -> str:
    ax, ay = at
    body = [
        f'  (footprint "Conn_{ref}" (layer "F.Cu") (uuid "{uid()}")',
        f'    (at {ax:.3f} {ay:.3f})',
        ref_text(ref),
    ]
    for i, (num, net) in enumerate(pins):
        body.append(pad(num, 0, i * PITCH, net))
    h = (len(pins) - 1) * PITCH
    body.append(
        f'    (fp_rect (start -1.6 -1.6) (end 1.6 {h + 1.6}) '
        f'(stroke (width 0.12) (type solid)) (fill none) (layer "F.SilkS") (uuid "{uid()}"))'
    )
    body.append("  )")
    return "\n".join(body)


def fp_header_h(ref: str, at: tuple[float, float], pins: list[tuple[str, str]]) -> str:
    """Horizontal 1xn along +X."""
    ax, ay = at
    body = [
        f'  (footprint "Conn_{ref}" (layer "F.Cu") (uuid "{uid()}")',
        f'    (at {ax:.3f} {ay:.3f})',
        ref_text(ref),
    ]
    for i, (num, net) in enumerate(pins):
        body.append(pad(num, i * PITCH, 0, net))
    w = (len(pins) - 1) * PITCH
    body.append(
        f'    (fp_rect (start -1.6 -1.6) (end {w + 1.6} 1.6) '
        f'(stroke (width 0.12) (type solid)) (fill none) (layer "F.SilkS") (uuid "{uid()}"))'
    )
    body.append("  )")
    return "\n".join(body)


def fp_header_2x(ref: str, at: tuple[float, float], pins: list[tuple[str, str]], rows: int) -> str:
    ax, ay = at
    body = [
        f'  (footprint "Conn_{ref}" (layer "F.Cu") (uuid "{uid()}")',
        f'    (at {ax:.3f} {ay:.3f})',
        ref_text(ref),
    ]
    for num, net in pins:
        n = int(num)
        row = (n - 1) // 2
        col = 0 if n % 2 == 1 else 1
        body.append(pad(num, col * PITCH, row * PITCH, net))
    body.append(
        f'    (fp_rect (start -1.6 -1.6) (end {PITCH + 1.6} {(rows - 1) * PITCH + 1.6}) '
        f'(stroke (width 0.12) (type solid)) (fill none) (layer "F.SilkS") (uuid "{uid()}"))'
    )
    body.append("  )")
    return "\n".join(body)


def fp_pwr(ref: str, at: tuple[float, float], nets: list[tuple[str, str]], pitch: float = 5.0, size: float = 3.2, drill: float = 1.8) -> str:
    ax, ay = at
    body = [
        f'  (footprint "Pwr_{ref}" (layer "F.Cu") (uuid "{uid()}")',
        f'    (at {ax:.3f} {ay:.3f})',
        ref_text(ref),
    ]
    for i, (num, net) in enumerate(nets):
        body.append(pad(num, i * pitch, 0, net, size=size, drill=drill))
    body.append("  )")
    return "\n".join(body)


def fp_m3(ref: str, at: tuple[float, float]) -> str:
    ax, ay = at
    return f"""  (footprint "Mount_M3" (layer "F.Cu") (uuid "{uid()}")
    (at {ax:.3f} {ay:.3f})
{ref_text(ref)}
    (pad "1" thru_hole circle (at 0 0) (size 6.0 6.0) (drill 3.2) (layers "*.Cu" "*.Mask") (net 0 "") (uuid "{uid()}"))
  )"""


def track(x1: float, y1: float, x2: float, y2: float, net: str, width: float, layer: str) -> str:
    return (
        f'  (segment (start {x1:.3f} {y1:.3f}) (end {x2:.3f} {y2:.3f}) '
        f'(width {width}) (layer "{layer}") (net {NET_ID[net]}) (uuid "{uid()}"))'
    )


def route_hv(
    a: tuple[float, float],
    b: tuple[float, float],
    net: str,
    channel_y: float,
    width: float = 0.3,
    layer: str = "F.Cu",
    escape_x: float | None = None,
) -> list[str]:
    """Fanout with optional unique escape_x so verticals don't stack on one column."""
    x1, y1 = a
    x2, y2 = b
    out: list[str] = []
    ex = x1 if escape_x is None else escape_x
    if abs(x1 - ex) > 0.05:
        out.append(track(x1, y1, ex, y1, net, width, layer))
    if abs(y1 - channel_y) > 0.05:
        out.append(track(ex, y1, ex, channel_y, net, width, layer))
    if abs(ex - x2) > 0.05:
        out.append(track(ex, channel_y, x2, channel_y, net, width, layer))
    if abs(y2 - channel_y) > 0.05:
        out.append(track(x2, channel_y, x2, y2, net, width, layer))
    return out


def zone(net: str, layer: str, pts: list[tuple[float, float]], clearance: float = 0.35, min_t: float = 0.25) -> str:
    nid = NET_ID[net]
    xy = " ".join(f"(xy {x} {y})" for x, y in pts)
    return f"""  (zone (net {nid}) (net_name "{net}") (layer "{layer}") (uuid "{uid()}")
    (hatch edge 0.5)
    (connect_pads (clearance {clearance}))
    (min_thickness {min_t})
    (filled_areas_thickness no)
    (fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5))
    (polygon (pts {xy}))
  )"""


def build() -> str:
    parts: list[str] = []
    tracks: list[str] = []

    # Power column
    jbat = (10, 12)
    f1 = (24, 12)
    sw1 = (24, 22)
    jvm = (10, 40)
    jk11 = (10, 50)
    buck = (10, 62)
    jp1 = (10, 78)
    parts += [
        fp_pwr("JBAT", jbat, [("1", "VBAT"), ("2", "GND")], pitch=8.0, size=3.5, drill=2.2),
        fp_pwr("F1", f1, [("1", "VBAT"), ("2", "VBAT_F")], pitch=8.0, size=2.4, drill=1.2),
        fp_pwr("SW1", sw1, [("1", "VBAT_F"), ("2", "VM")], pitch=5.0, size=2.4, drill=1.2),
        fp_pwr("JVM", jvm, [("1", "VM"), ("2", "GND")], pitch=5.08, size=2.8, drill=1.5),
        fp_pwr("JK11", jk11, [("1", "VM"), ("2", "GND")], pitch=5.08, size=2.8, drill=1.5),
        fp_pwr("UBUCK", buck, [("1", "VM"), ("2", "GND"), ("3", "V_SERVO"), ("4", "GND")], pitch=3.5, size=2.2, drill=1.1),
        fp_pwr("JP1", jp1, [("1", "+5V_LOGIC"), ("2", "+5V_LOGIC")], pitch=2.54, size=1.7, drill=1.0),
    ]

    # P1 K11C
    p1_at = (42, 8)
    p1_pins = []
    for n in range(1, 31):
        if n == 1:
            net = "+3V3"
        elif n in (2, 4):
            net = "+5V_LOGIC"
        elif n in (3, 6, 13, 23, 29):
            net = "GND"
        elif n == 15:
            net = "UART_K11C_RX"
        elif n == 16:
            net = "I2C3_SCL"
        elif n == 17:
            net = "UART_K11C_TX"
        elif n == 18:
            net = "I2C3_SDA"
        elif n in (25, 27):
            net = "NC_DEBUG"
        else:
            net = ""
        p1_pins.append((str(n), net))
    parts.append(fp_header_2x("P1", p1_at, p1_pins, 15))

    # S3 headers — keep inside board: 8 + 21*2.54 = 61.34
    p2_at = (78, 8)
    p2_map = {
        4: "PWMA", 5: "AIN1", 6: "AIN2", 7: "PWMB", 8: "BIN1", 9: "BIN2",
        10: "UART_K11C_RX", 11: "UART_K11C_TX", 12: "STBY",
        13: "ENC_A_B", 14: "ENC_A_A", 15: "PWMC", 16: "CIN1", 17: "CIN2",
        18: "PWMD", 19: "ENC_B_B",
    }
    parts.append(fp_header_v("P2", p2_at, [(str(i), p2_map.get(i, "")) for i in range(1, 23)]))

    p3_at = (98, 8)
    p3_map = {
        4: "SERVO_PAN", 5: "SERVO_TILT", 6: "ENC_D_A", 7: "ENC_C_B",
        9: "ENC_D_B", 10: "ENC_B_A", 17: "ENC_C_A", 18: "DIN1", 19: "DIN2",
    }
    parts.append(fp_header_v("P3", p3_at, [(str(i), p3_map.get(i, "")) for i in range(1, 23)]))

    # Bottom horizontal connectors — stay above y=H-6
    p4_at = (40, 88)
    p4_nets = ["STBY", "PWMA", "AIN1", "AIN2", "PWMB", "BIN1", "BIN2", "PWMC", "CIN1", "CIN2", "PWMD", "DIN1", "DIN2", "GND", "+5V_LOGIC"]
    parts.append(fp_header_h("P4", p4_at, [(str(i + 1), n) for i, n in enumerate(p4_nets)]))

    p5_at = (40, 78)
    p5_nets = ["ENC_A_A", "ENC_A_B", "ENC_B_A", "ENC_B_B", "ENC_C_A", "ENC_C_B", "ENC_D_A", "ENC_D_B", "+3V3", "GND"]
    parts.append(fp_header_h("P5", p5_at, [(str(i + 1), n) for i, n in enumerate(p5_nets)]))

    p6_at = (118, 10)
    parts.append(fp_header_v("P6", p6_at, [
        ("1", "SERVO_PAN"), ("2", "V_SERVO"), ("3", "GND"),
        ("4", "SERVO_TILT"), ("5", "V_SERVO"), ("6", "GND"),
    ]))

    p7_at = (118, 40)
    parts.append(fp_header_v("P7", p7_at, [("1", "+3V3"), ("2", "GND"), ("3", "I2C3_SCL"), ("4", "I2C3_SDA")]))

    for i, pos in enumerate([(4, 4), (W - 4, 4), (4, H - 4), (W - 4, H - 4)], 1):
        parts.append(fp_m3(f"H{i}", pos))

    def p1(n: int) -> tuple[float, float]:
        return p1_at[0] + (0 if n % 2 == 1 else PITCH), p1_at[1] + ((n - 1) // 2) * PITCH

    def p2(n: int) -> tuple[float, float]:
        return p2_at[0], p2_at[1] + (n - 1) * PITCH

    def p3(n: int) -> tuple[float, float]:
        return p3_at[0], p3_at[1] + (n - 1) * PITCH

    def p4(n: int) -> tuple[float, float]:
        return p4_at[0] + (n - 1) * PITCH, p4_at[1]

    def p5(n: int) -> tuple[float, float]:
        return p5_at[0] + (n - 1) * PITCH, p5_at[1]

    def p6(n: int) -> tuple[float, float]:
        return p6_at[0], p6_at[1] + (n - 1) * PITCH

    def p7(n: int) -> tuple[float, float]:
        return p7_at[0], p7_at[1] + (n - 1) * PITCH

    # No scripted Manhattan tracks: they crossed pads/headers and created
    # false shorts. Pads carry net names (ratsnest). Power uses copper zones.
    # Route remaining nets interactively in KiCad / FreeRouting.
    _ = (p1, p2, p3, p4, p5, p6, p7, route_hv)  # kept for future route helpers

    layers = """  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
    (32 "B.Adhes" user)
    (33 "F.Adhes" user)
    (34 "B.Paste" user)
    (35 "F.Paste" user)
    (36 "B.SilkS" user)
    (37 "F.SilkS" user)
    (38 "B.Mask" user)
    (39 "F.Mask" user)
    (40 "Dwgs.User" user)
    (41 "Cmts.User" user)
    (42 "Eco1.User" user)
    (43 "Eco2.User" user)
    (44 "Edge.Cuts" user)
    (45 "F.CrtYd" user)
    (46 "B.CrtYd" user)
    (47 "F.Fab" user)
    (48 "B.Fab" user)
  )"""

    zones = "\n".join([
        zone("GND", "B.Cu", [(2, 2), (W - 2, 2), (W - 2, H - 2), (2, H - 2)], 0.4, 0.25),
        zone("GND", "F.Cu", [(2, 2), (32, 2), (32, 34), (2, 34)], 0.4, 0.25),
        zone("VM", "F.Cu", [(2, 35), (32, 35), (32, 72), (2, 72)], 0.5, 0.4),
    ])

    return f"""(kicad_pcb
  (version 20240108)
  (generator "shuxin_carrier_pcb_v11")
  (generator_version "1.1")
  (general (thickness 1.6) (legacy_teardrops no))
  (paper "A4")
  (title_block
    (title "shuxin Carrier V1.1")
    (date "2026-11-12")
    (rev "B")
    (company "pureheartrobotics")
  )
{layers}
  (setup
    (pad_to_mask_clearance 0.05)
    (allow_soldermask_bridges_in_footprints no)
  )
{net_decl()}
  (gr_rect (start 0 0) (end {W} {H})
    (stroke (width 0.1) (type default)) (fill none) (layer "Edge.Cuts") (uuid "{uid()}"))
  (gr_text "shuxin CARRIER V1.1  {W:.0f}x{H:.0f}mm\\nJP1 off when USB-flash S3 | P1-25/27 NC"
    (at 36 96) (layer "F.SilkS") (uuid "{uid()}")
    (effects (font (size 1.2 1.2) (thickness 0.15)) (justify left bottom)))
{chr(10).join(parts)}
{chr(10).join(tracks)}
{zones}
)
"""


def main() -> None:
    text = build()
    OUT.write_text(text, encoding="utf-8")
    print(f"Wrote {OUT} ({len(text)} bytes) board={W}x{H}mm")


if __name__ == "__main__":
    main()
