#!/usr/bin/env python3
"""Carrier V1.2 — spaced footprint placement + copper zones (KiCad 10).

Signal copper is produced by FreeRouting (see gen/run_freerouting.py).
This script only places connectors/power and pours GND/VM zones.
"""
from __future__ import annotations

import uuid
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "carrier_v1.kicad_pcb"
W, H = 160.0, 110.0
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


def pad(num: str, x: float, y: float, net: str, size: float = 1.6, drill: float = 1.0) -> str:
    shape = "rect" if str(num) == "1" else "circle"
    return (
        f'    (pad "{num}" thru_hole {shape} (at {x:.3f} {y:.3f}) (size {size} {size}) '
        f'(drill {drill}) (layers "*.Cu" "*.Mask") (net {NET_ID[net]} "{net}") '
        f'(uuid "{uid()}"))'
    )


def props(ref: str) -> str:
    return (
        f'    (property "Reference" "{ref}" (at 0 -2.8 0) (layer "F.SilkS") (uuid "{uid()}")\n'
        f'      (effects (font (size 1.0 1.0) (thickness 0.15)))\n'
        f'    )\n'
        f'    (property "Value" "{ref}" (at 0 2 0) (layer "F.Fab") (uuid "{uid()}")\n'
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


def fp_v(ref: str, at, pins):
    ax, ay = at
    body = [f'  (footprint "Conn_{ref}" (layer "F.Cu") (uuid "{uid()}")', f'    (at {ax:.3f} {ay:.3f})', props(ref)]
    for i, (num, net) in enumerate(pins):
        body.append(pad(num, 0, i * PITCH, net))
    h = (len(pins) - 1) * PITCH
    body.append(
        f'    (fp_rect (start -1.5 -1.5) (end 1.5 {h + 1.5}) (stroke (width 0.12) (type solid)) '
        f'(fill none) (layer "F.SilkS") (uuid "{uid()}"))'
    )
    body.append("  )")
    return "\n".join(body)


def fp_h(ref: str, at, pins):
    ax, ay = at
    body = [f'  (footprint "Conn_{ref}" (layer "F.Cu") (uuid "{uid()}")', f'    (at {ax:.3f} {ay:.3f})', props(ref)]
    for i, (num, net) in enumerate(pins):
        body.append(pad(num, i * PITCH, 0, net))
    w = (len(pins) - 1) * PITCH
    body.append(
        f'    (fp_rect (start -1.5 -1.5) (end {w + 1.5} 1.5) (stroke (width 0.12) (type solid)) '
        f'(fill none) (layer "F.SilkS") (uuid "{uid()}"))'
    )
    body.append("  )")
    return "\n".join(body)


def fp_2x(ref: str, at, pins, rows: int):
    ax, ay = at
    body = [f'  (footprint "Conn_{ref}" (layer "F.Cu") (uuid "{uid()}")', f'    (at {ax:.3f} {ay:.3f})', props(ref)]
    for num, net in pins:
        n = int(num)
        body.append(pad(num, (0 if n % 2 else PITCH), ((n - 1) // 2) * PITCH, net))
    body.append(
        f'    (fp_rect (start -1.5 -1.5) (end {PITCH + 1.5} {(rows - 1) * PITCH + 1.5}) '
        f'(stroke (width 0.12) (type solid)) (fill none) (layer "F.SilkS") (uuid "{uid()}"))'
    )
    body.append("  )")
    return "\n".join(body)


def fp_pwr(ref, at, nets, pitch=5.0, size=3.0, drill=1.6):
    ax, ay = at
    body = [f'  (footprint "Pwr_{ref}" (layer "F.Cu") (uuid "{uid()}")', f'    (at {ax:.3f} {ay:.3f})', props(ref)]
    for i, (num, net) in enumerate(nets):
        body.append(pad(num, i * pitch, 0, net, size=size, drill=drill))
    body.append("  )")
    return "\n".join(body)


def fp_m3(ref, at):
    ax, ay = at
    return f"""  (footprint "Mount_M3" (layer "F.Cu") (uuid "{uid()}")
    (at {ax:.3f} {ay:.3f})
{props(ref)}
    (pad "1" thru_hole circle (at 0 0) (size 6 6) (drill 3.2) (layers "*.Cu" "*.Mask") (net 0 "") (uuid "{uid()}"))
  )"""


def track(x1, y1, x2, y2, net, width, layer):
    return (
        f'  (segment (start {x1:.3f} {y1:.3f}) (end {x2:.3f} {y2:.3f}) '
        f'(width {width}) (layer "{layer}") (net {NET_ID[net]}) (uuid "{uid()}"))'
    )


def via(x, y, net):
    return (
        f'  (via (at {x:.3f} {y:.3f}) (size 0.8) (drill 0.4) (layers "F.Cu" "B.Cu") '
        f'(net {NET_ID[net]}) (uuid "{uid()}"))'
    )


def poly(pts, net, width, layer):
    out = []
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        if abs(x1 - x2) < 0.01 and abs(y1 - y2) < 0.01:
            continue
        out.append(track(x1, y1, x2, y2, net, width, layer))
    return out


def route_hv_via(src, dst, net, lane_x: float, bus_y: float, width: float = 0.28):
    """Escape H on F, vertical trunk on B, horizontal bus on F, vertical drop on B.

    Pattern avoids same-layer crossings when each net has unique (lane_x, bus_y).
    Thru-hole pads stitch layers at endpoints; vias stitch at elbows.
    """
    sx, sy = src
    dx, dy = dst
    out = []
    # H escape on F to lane
    out += poly([(sx, sy), (lane_x, sy)], net, width, "F.Cu")
    out.append(via(lane_x, sy, net))
    # V on B to bus
    out += poly([(lane_x, sy), (lane_x, bus_y)], net, width, "B.Cu")
    out.append(via(lane_x, bus_y, net))
    # H on F along bus
    out += poly([(lane_x, bus_y), (dx, bus_y)], net, width, "F.Cu")
    out.append(via(dx, bus_y, net))
    # V on B to dest
    out += poly([(dx, bus_y), (dx, dy)], net, width, "B.Cu")
    return out


def zone(net, layer, pts, clearance=0.4, min_t=0.25):
    xy = " ".join(f"(xy {x} {y})" for x, y in pts)
    return f"""  (zone (net {NET_ID[net]}) (net_name "{net}") (layer "{layer}") (uuid "{uid()}")
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

    # --- placement (leave free corridors) ---
    # Power left
    jbat, f1, sw1 = (12, 14), (28, 14), (28, 24)
    jvm, jk11, buck, jp1 = (12, 42), (12, 52), (12, 64), (12, 80)
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
    p1_at = (45, 10)
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
    parts.append(fp_2x("P1", p1_at, p1_pins, 15))

    # S3 — leave corridor x=60..84 between P1 and P2
    p2_at = (88, 10)   # left header
    p3_at = (110, 10)  # right header
    p2_map = {
        4: "PWMA", 5: "AIN1", 6: "AIN2", 7: "PWMB", 8: "BIN1", 9: "BIN2",
        10: "UART_K11C_RX", 11: "UART_K11C_TX", 12: "STBY",
        13: "ENC_A_B", 14: "ENC_A_A", 15: "PWMC", 16: "CIN1", 17: "CIN2",
        18: "PWMD", 19: "ENC_B_B",
    }
    p3_map = {
        4: "SERVO_PAN", 5: "SERVO_TILT", 6: "ENC_D_A", 7: "ENC_C_B",
        9: "ENC_D_B", 10: "ENC_B_A", 17: "ENC_C_A", 18: "DIN1", 19: "DIN2",
    }
    parts.append(fp_v("P2", p2_at, [(str(i), p2_map.get(i, "")) for i in range(1, 23)]))
    parts.append(fp_v("P3", p3_at, [(str(i), p3_map.get(i, "")) for i in range(1, 23)]))

    # Encoders left-bottom (under power/P1), control right-bottom (under S3) — no x overlap
    p5_at = (40, 92)   # encoders
    p4_at = (88, 100)  # D24A control under P2/P3
    p4_nets = ["STBY", "PWMA", "AIN1", "AIN2", "PWMB", "BIN1", "BIN2", "PWMC", "CIN1", "CIN2", "PWMD", "DIN1", "DIN2", "GND", "+5V_LOGIC"]
    p5_nets = ["ENC_A_A", "ENC_A_B", "ENC_B_A", "ENC_B_B", "ENC_C_A", "ENC_C_B", "ENC_D_A", "ENC_D_B", "+3V3", "GND"]
    parts.append(fp_h("P4", p4_at, [(str(i + 1), n) for i, n in enumerate(p4_nets)]))
    parts.append(fp_h("P5", p5_at, [(str(i + 1), n) for i, n in enumerate(p5_nets)]))

    p6_at = (132, 12)
    p7_at = (132, 42)
    parts.append(fp_v("P6", p6_at, [
        ("1", "SERVO_PAN"), ("2", "V_SERVO"), ("3", "GND"),
        ("4", "SERVO_TILT"), ("5", "V_SERVO"), ("6", "GND"),
    ]))
    parts.append(fp_v("P7", p7_at, [("1", "+3V3"), ("2", "GND"), ("3", "I2C3_SCL"), ("4", "I2C3_SDA")]))

    for i, pos in enumerate([(4, 4), (W - 4, 4), (4, H - 4), (W - 4, H - 4)], 1):
        parts.append(fp_m3(f"H{i}", pos))

    def P1(n):
        return p1_at[0] + (0 if n % 2 else PITCH), p1_at[1] + ((n - 1) // 2) * PITCH

    def P2(n):
        return p2_at[0], p2_at[1] + (n - 1) * PITCH

    def P3(n):
        return p3_at[0], p3_at[1] + (n - 1) * PITCH

    def P4(n):
        return p4_at[0] + (n - 1) * PITCH, p4_at[1]

    def P5(n):
        return p5_at[0] + (n - 1) * PITCH, p5_at[1]

    def P6(n):
        return p6_at[0], p6_at[1] + (n - 1) * PITCH

    def P7(n):
        return p7_at[0], p7_at[1] + (n - 1) * PITCH

    # --- channel routes ---
    # Pads carry net names; FreeRouting fills copper (gen/run_freerouting.py).
    _ = (P1, P2, P3, P4, P5, P6, P7, jbat, f1, sw1, jvm, jk11, buck, jp1, route_hv_via, poly)

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
        zone("GND", "B.Cu", [(2, 2), (W - 2, 2), (W - 2, H - 2), (2, H - 2)]),
        zone("GND", "F.Cu", [(2, 2), (34, 2), (34, 36), (2, 36)]),
        zone("VM", "F.Cu", [(2, 38), (34, 38), (34, 76), (2, 76)], 0.5, 0.4),
    ])

    return f"""(kicad_pcb
  (version 20240108)
  (generator "shuxin_carrier_pcb_v12")
  (generator_version "1.2")
  (general (thickness 1.6) (legacy_teardrops no))
  (paper "A4")
  (title_block
    (title "shuxin Carrier V1.2")
    (date "2026-11-12")
    (rev "C")
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
  (gr_text "shuxin CARRIER V1.2  {W:.0f}x{H:.0f}mm  channel-routed\\nJP1 off when USB-flash S3 | P1-25/27 NC"
    (at 40 107) (layer "F.SilkS") (uuid "{uid()}")
    (effects (font (size 1.2 1.2) (thickness 0.15)) (justify left bottom)))
{chr(10).join(parts)}
{chr(10).join(tracks)}
{zones}
)
"""


def main() -> None:
    text = build()
    OUT.write_text(text, encoding="utf-8")
    print(f"Wrote {OUT} ({len(text)} bytes) board={W}x{H} tracks={text.count('(segment')}")


if __name__ == "__main__":
    main()
