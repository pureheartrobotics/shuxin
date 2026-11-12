#!/usr/bin/env python3
"""Carrier V1.3 — XH2.54 harness + DevKit/K11C headers (placement + zones).

Signal copper: gen/run_freerouting.py
"""
from __future__ import annotations

import uuid
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "carrier_v1.kicad_pcb"
W, H = 160.0, 110.0
PITCH = 2.54  # XH2.54 / Dupont pitch


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
    shape = "rect" if str(num) == "1" else "circle"
    return (
        f'    (pad "{num}" thru_hole {shape} (at {x:.3f} {y:.3f}) (size {size} {size}) '
        f'(drill {drill}) (layers "*.Cu" "*.Mask") (net {NET_ID[net]} "{net}") '
        f'(uuid "{uid()}"))'
    )


def props(ref: str, value: str = "") -> str:
    val = value or ref
    return (
        f'    (property "Reference" "{ref}" (at 0 -3.2 0) (layer "F.SilkS") (uuid "{uid()}")\n'
        f'      (effects (font (size 1.0 1.0) (thickness 0.15)))\n'
        f'    )\n'
        f'    (property "Value" "{val}" (at 0 3.2 0) (layer "F.Fab") (uuid "{uid()}")\n'
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


def fp_header_v(ref: str, at, pins, value="PinHeader"):
    ax, ay = at
    body = [f'  (footprint "Hdr_{ref}" (layer "F.Cu") (uuid "{uid()}")', f'    (at {ax:.3f} {ay:.3f})', props(ref, value)]
    for i, (num, net) in enumerate(pins):
        body.append(pad(num, 0, i * PITCH, net))
    h = (len(pins) - 1) * PITCH
    body.append(
        f'    (fp_rect (start -1.5 -1.5) (end 1.5 {h + 1.5}) (stroke (width 0.12) (type solid)) '
        f'(fill none) (layer "F.SilkS") (uuid "{uid()}"))'
    )
    body.append("  )")
    return "\n".join(body)


def fp_header_2x(ref: str, at, pins, rows: int):
    ax, ay = at
    body = [f'  (footprint "Hdr_{ref}" (layer "F.Cu") (uuid "{uid()}")', f'    (at {ax:.3f} {ay:.3f})', props(ref, "2x15")]
    for num, net in pins:
        n = int(num)
        body.append(pad(num, (0 if n % 2 else PITCH), ((n - 1) // 2) * PITCH, net))
    body.append(
        f'    (fp_rect (start -1.5 -1.5) (end {PITCH + 1.5} {(rows - 1) * PITCH + 1.5}) '
        f'(stroke (width 0.12) (type solid)) (fill none) (layer "F.SilkS") (uuid "{uid()}"))'
    )
    body.append("  )")
    return "\n".join(body)


def fp_xh(ref: str, at, pins, value: str):
    """XH2.54 vertical male, pins along +X, keying silk on -Y."""
    ax, ay = at
    n = len(pins)
    body = [
        f'  (footprint "XH254_{ref}" (layer "F.Cu") (uuid "{uid()}")',
        f'    (at {ax:.3f} {ay:.3f})',
        props(ref, value),
    ]
    for i, (num, net) in enumerate(pins):
        # slightly oval-ish via larger Y size on pad1 already rect
        body.append(pad(num, i * PITCH, 0, net, size=1.7, drill=1.0))
    w = (n - 1) * PITCH
    # XH-like shroud outline
    body.append(
        f'    (fp_rect (start -2.2 -2.8) (end {w + 2.2} 2.8) (stroke (width 0.12) (type solid)) '
        f'(fill none) (layer "F.SilkS") (uuid "{uid()}"))'
    )
    body.append(
        f'    (fp_line (start -1.0 -2.8) (end -1.0 -1.6) (stroke (width 0.12) (type solid)) '
        f'(layer "F.SilkS") (uuid "{uid()}"))'
    )
    body.append(
        f'    (fp_text user "1" (at -0.2 -3.6) (layer "F.SilkS") (uuid "{uid()}")\n'
        f'      (effects (font (size 0.8 0.8) (thickness 0.12))))'
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
    p1_at = (42, 10)
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

    # Optional XH UART breakout (same nets as P1 UART)
    parts.append(
        fp_xh(
            "J_UART",
            (58, 52),
            [("1", "UART_K11C_TX"), ("2", "UART_K11C_RX"), ("3", "GND")],
            "XH2.54-3P",
        )
    )

    # S3 DevKit
    p2_at, p3_at = (88, 10), (110, 10)
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
    parts.append(fp_header_v("P2", p2_at, [(str(i), p2_map.get(i, "")) for i in range(1, 23)], "S3-L"))
    parts.append(fp_header_v("P3", p3_at, [(str(i), p3_map.get(i, "")) for i in range(1, 23)], "S3-R"))

    # D24A control XH
    parts.append(
        fp_xh(
            "J_CTRL_AB",
            (72, 98),
            [
                ("1", "STBY"),
                ("2", "PWMA"),
                ("3", "AIN1"),
                ("4", "AIN2"),
                ("5", "PWMB"),
                ("6", "BIN1"),
                ("7", "BIN2"),
                ("8", "GND"),
            ],
            "XH2.54-8P",
        )
    )
    parts.append(
        fp_xh(
            "J_CTRL_CD",
            (100, 98),
            [
                ("1", "PWMC"),
                ("2", "CIN1"),
                ("3", "CIN2"),
                ("4", "PWMD"),
                ("5", "DIN1"),
                ("6", "DIN2"),
                ("7", "+5V_LOGIC"),
                ("8", "GND"),
            ],
            "XH2.54-8P",
        )
    )

    # Encoders XH 4P
    enc = [
        ("J_ENC_A", (36, 88), "ENC_A_A", "ENC_A_B"),
        ("J_ENC_B", (52, 88), "ENC_B_A", "ENC_B_B"),
        ("J_ENC_C", (68, 88), "ENC_C_A", "ENC_C_B"),
        ("J_ENC_D", (84, 88), "ENC_D_A", "ENC_D_B"),
    ]
    for ref, at, a, b in enc:
        parts.append(fp_xh(ref, at, [("1", a), ("2", b), ("3", "+3V3"), ("4", "GND")], "XH2.54-4P"))

    # Servos + ToF
    parts.append(fp_xh("J_SERVO_PAN", (132, 14), [("1", "SERVO_PAN"), ("2", "V_SERVO"), ("3", "GND")], "XH2.54-3P"))
    parts.append(fp_xh("J_SERVO_TILT", (132, 28), [("1", "SERVO_TILT"), ("2", "V_SERVO"), ("3", "GND")], "XH2.54-3P"))
    parts.append(fp_xh("J_TOF", (132, 48), [("1", "+3V3"), ("2", "GND"), ("3", "I2C3_SCL"), ("4", "I2C3_SDA")], "XH2.54-4P"))

    for i, pos in enumerate([(4, 4), (W - 4, 4), (4, H - 4), (W - 4, H - 4)], 1):
        parts.append(fp_m3(f"H{i}", pos))

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
  (generator "shuxin_carrier_pcb_v13")
  (generator_version "1.3")
  (general (thickness 1.6) (legacy_teardrops no))
  (paper "A4")
  (title_block
    (title "shuxin Carrier V1.3 XH2.54")
    (date "2026-11-12")
    (rev "D")
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
  (gr_text "shuxin CARRIER V1.3  {W:.0f}x{H:.0f}mm  harness=XH2.54\\nJP1 off when USB-flash S3 | P1-25/27 NC"
    (at 40 107) (layer "F.SilkS") (uuid "{uid()}")
    (effects (font (size 1.15 1.15) (thickness 0.15)) (justify left bottom)))
{chr(10).join(parts)}
{zones}
)
"""


def main() -> None:
    text = build()
    OUT.write_text(text, encoding="utf-8")
    print(f"Wrote {OUT} ({len(text)} bytes) board={W}x{H}")


if __name__ == "__main__":
    main()
