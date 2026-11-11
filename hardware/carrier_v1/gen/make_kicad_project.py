#!/usr/bin/env python3
"""Generate KiCad 8 project + single-sheet schematic for shuxin carrier_v1.

No KiCad install required to generate; open the result in KiCad 8+.
"""
from __future__ import annotations

import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT


def uid() -> str:
    return str(uuid.uuid4())


def esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def symbol_conn(lib_id: str, ref: str, value: str, x: float, y: float, pins: list[tuple[int, str, str]]) -> str:
    """Minimal schematic symbol instance + on-sheet pin labels as text nets via labels."""
    # Use generic connector units drawn as boxes with hierarchical labels nearby.
    # KiCad needs library symbols; we emit graphical boxes + global labels for fab handoff
    # that still open, and a companion netlist. For true ERC, user can replace with
    # Connector_Generic symbols in KiCad GUI.
    body = [
        f'  (text "{esc(ref)}\\n{esc(value)}" (exclude_from_sim no) (at {x} {y - 5} 0)',
        f'    (effects (font (size 1.27 1.27)) (justify left bottom))',
        f'    (uuid "{uid()}")',
        f'  )',
        f'  (rectangle (start {x} {y}) (end {x + 30} {y + max(8, len(pins) * 2.54 + 2)})',
        f'    (stroke (width 0.254) (type solid)) (fill (type none))',
        f'    (uuid "{uid()}")',
        f'  )',
    ]
    for i, (num, name, net) in enumerate(pins):
        py = y + 2 + i * 2.54
        body.append(
            f'  (text "{num}:{esc(name)}" (exclude_from_sim no) (at {x + 1} {py} 0)\n'
            f'    (effects (font (size 0.9 0.9)) (justify left))\n'
            f'    (uuid "{uid()}")\n'
            f'  )'
        )
        body.append(
            f'  (global_label "{esc(net)}" (shape input) (at {x + 32} {py} 0) (fields_autoplaced yes)\n'
            f'    (effects (font (size 1.0 1.0)) (justify left))\n'
            f'    (uuid "{uid()}")\n'
            f'    (property "Intersheetrefs" "${{INTERSHEET_REFS}}" (at {x + 32} {py} 0)\n'
            f'      (effects (font (size 1.27 1.27)) hide)\n'
            f'    )\n'
            f'  )'
        )
    return "\n".join(body)


def write_pro() -> None:
    (OUT / "carrier_v1.kicad_pro").write_text(
        """{
  "board": {
    "design_settings": {
      "defaults": {
        "board_thickness": 1.6,
        "copper_finish": "None",
        "edge_connector": "No"
      }
    }
  },
  "meta": {
    "filename": "carrier_v1.kicad_pro",
    "version": 1
  },
  "sheets": [
    ["root", ""]
  ],
  "text_variables": {},
  "libraries": {
    "pinned_footprint_libs": [],
    "pinned_symbol_libs": []
  }
}
""",
        encoding="utf-8",
    )


def write_sch() -> None:
    blocks: list[str] = []

    blocks.append(
        symbol_conn(
            "P1",
            "P1",
            "K11C 2x15",
            20,
            20,
            [
                (1, "3V3", "+3V3"),
                (3, "GND", "GND"),
                (15, "UART7_RX", "UART_K11C_RX"),
                (16, "I2C3_SCL", "I2C3_SCL"),
                (17, "UART7_TX", "UART_K11C_TX"),
                (18, "I2C3_SDA", "I2C3_SDA"),
                (23, "GND", "GND"),
                (25, "DEBUG_RX", "NC_DEBUG"),
                (27, "DEBUG_TX", "NC_DEBUG"),
                (29, "GND", "GND"),
            ],
        )
    )

    blocks.append(
        symbol_conn(
            "P2",
            "P2",
            "S3 DevKit LEFT",
            80,
            20,
            [
                (4, "GPIO4", "PWMA"),
                (5, "GPIO5", "AIN1"),
                (6, "GPIO6", "AIN2"),
                (7, "GPIO7", "PWMB"),
                (8, "GPIO15", "BIN1"),
                (9, "GPIO16", "BIN2"),
                (10, "GPIO17", "UART_K11C_RX"),
                (11, "GPIO18", "UART_K11C_TX"),
                (12, "GPIO8", "STBY"),
                (13, "GPIO3", "ENC_A_B"),
                (14, "GPIO46", "ENC_A_A"),
                (15, "GPIO9", "PWMC"),
                (16, "GPIO10", "CIN1"),
                (17, "GPIO11", "CIN2"),
                (18, "GPIO12", "PWMD"),
                (19, "GPIO13", "ENC_B_B"),
            ],
        )
    )

    blocks.append(
        symbol_conn(
            "P3",
            "P3",
            "S3 DevKit RIGHT",
            140,
            20,
            [
                (4, "GPIO1", "SERVO_PAN"),
                (5, "GPIO2", "SERVO_TILT"),
                (6, "GPIO42", "ENC_D_A"),
                (7, "GPIO41", "ENC_C_B"),
                (9, "GPIO39", "ENC_D_B"),
                (10, "GPIO38", "ENC_B_A"),
                (17, "GPIO47", "ENC_C_A"),
                (18, "GPIO21", "DIN1"),
                (19, "GPIO14", "DIN2"),
            ],
        )
    )

    blocks.append(
        symbol_conn(
            "P4",
            "P4",
            "D24A CTRL",
            20,
            80,
            [
                (1, "STBY", "STBY"),
                (2, "PWMA", "PWMA"),
                (3, "AIN1", "AIN1"),
                (4, "AIN2", "AIN2"),
                (5, "PWMB", "PWMB"),
                (6, "BIN1", "BIN1"),
                (7, "BIN2", "BIN2"),
                (8, "PWMC", "PWMC"),
                (9, "CIN1", "CIN1"),
                (10, "CIN2", "CIN2"),
                (11, "PWMD", "PWMD"),
                (12, "DIN1", "DIN1"),
                (13, "DIN2", "DIN2"),
                (14, "GND", "GND"),
                (15, "+5V", "+5V_LOGIC"),
            ],
        )
    )

    blocks.append(
        symbol_conn(
            "P5",
            "P5",
            "ENCODERS",
            80,
            80,
            [
                (1, "E1A", "ENC_A_A"),
                (2, "E1B", "ENC_A_B"),
                (3, "E2A", "ENC_B_A"),
                (4, "E2B", "ENC_B_B"),
                (5, "E3A", "ENC_C_A"),
                (6, "E3B", "ENC_C_B"),
                (7, "E4A", "ENC_D_A"),
                (8, "E4B", "ENC_D_B"),
                (9, "3V3", "+3V3"),
                (10, "GND", "GND"),
            ],
        )
    )

    blocks.append(
        symbol_conn(
            "P6",
            "P6",
            "SERVOS",
            140,
            80,
            [
                (1, "PAN_SIG", "SERVO_PAN"),
                (2, "TILT_SIG", "SERVO_TILT"),
                (3, "V_SERVO", "V_SERVO"),
                (4, "GND", "GND"),
            ],
        )
    )

    blocks.append(
        symbol_conn(
            "P7",
            "P7",
            "ToF VL53",
            140,
            110,
            [
                (1, "3V3", "+3V3"),
                (2, "GND", "GND"),
                (3, "SCL", "I2C3_SCL"),
                (4, "SDA", "I2C3_SDA"),
            ],
        )
    )

    blocks.append(
        symbol_conn(
            "PWR",
            "PWR",
            "POWER TREE",
            20,
            130,
            [
                (1, "VBAT", "VBAT"),
                (2, "VM", "VM"),
                (3, "V_SERVO", "V_SERVO"),
                (4, "+5V_LOGIC", "+5V_LOGIC"),
                (5, "+3V3", "+3V3"),
                (6, "GND", "GND"),
            ],
        )
    )

    title = (
        '  (text "shuxin CARRIER V1 — interconnect board (not IC substrate)\\n'
        "K11C + ESP32-S3 DevKit + D24A harness + 8.4V servos + ToF I2C\\n"
        'See docs/CONNECTORS.md — do NOT wire DEBUG UART pins 25/27"'
        " (exclude_from_sim no) (at 20 10 0)\n"
        "    (effects (font (size 1.5 1.5)) (justify left bottom))\n"
        f'    (uuid "{uid()}")\n'
        "  )"
    )

    sch = f"""(kicad_sch
  (version 20231120)
  (generator "shuxin_carrier_gen")
  (generator_version "1.0")
  (uuid "{uid()}")
  (paper "A2")
  (title_block
    (title "shuxin Carrier V1")
    (date "2026-11-12")
    (rev "A")
    (company "pureheartrobotics")
    (comment 1 "Interconnect carrier: modules on sockets, zero Dupont")
    (comment 2 "Source of truth: docs/CONNECTORS.md + docs/nets.csv")
  )
{title}
{chr(10).join(blocks)}
  (sheet_instances
    (path "/" (page "1"))
  )
)
"""
    (OUT / "carrier_v1.kicad_sch").write_text(sch, encoding="utf-8")


def write_pcb_outline() -> None:
    """Minimal 2-layer board outline + courtyard notes for placement."""
    # 120 x 90 mm board
    w, h = 120.0, 90.0
    pcb = f"""(kicad_pcb
  (version 20240108)
  (generator "shuxin_carrier_gen")
  (generator_version "1.0")
  (general
    (thickness 1.6)
    (legacy_teardrops no)
  )
  (paper "A4")
  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
    (32 "B.Adhes" user "B.Adhesive")
    (33 "F.Adhes" user "F.Adhesive")
    (34 "B.Paste" user)
    (35 "F.Paste" user)
    (36 "B.SilkS" user "B.Silkscreen")
    (37 "F.SilkS" user "F.Silkscreen")
    (38 "B.Mask" user)
    (39 "F.Mask" user)
    (40 "Dwgs.User" user "User.Drawings")
    (41 "Cmts.User" user "User.Comments")
    (42 "Eco1.User" user "User.Eco1")
    (43 "Eco2.User" user "User.Eco2")
    (44 "Edge.Cuts" user)
    (45 "F.CrtYd" user "F.Courtyard")
    (46 "B.CrtYd" user "B.Courtyard")
    (47 "F.Fab" user)
    (48 "B.Fab" user)
  )
  (setup
    (pad_to_mask_clearance 0)
    (allow_soldermask_bridges_in_footprints no)
  )
  (net 0 "")
  (gr_rect (start 0 0) (end {w} {h})
    (stroke (width 0.1) (type default)) (fill none) (layer "Edge.Cuts") (uuid "{uid()}"))
  (gr_text "CARRIER V1 120x90mm\\nPlace: P1 K11C | P2/P3 S3 DevKit | P4 D24A | P5 ENC | P6 Servo | P7 ToF | PWR left"
    (at 5 5) (layer "Cmts.User") (uuid "{uid()}")
    (effects (font (size 1.5 1.5) (thickness 0.2)) (justify left top)))
  (gr_text "Keep motor VM / servo 8.4V away from UART+I2C\\nStar GND near D24A connector"
    (at 5 80) (layer "Cmts.User") (uuid "{uid()}")
    (effects (font (size 1.2 1.2) (thickness 0.15)) (justify left top)))
)
"""
    (OUT / "carrier_v1.kicad_pcb").write_text(pcb, encoding="utf-8")


def main() -> None:
    write_pro()
    write_sch()
    write_pcb_outline()
    print(f"Wrote KiCad project under {OUT}")


if __name__ == "__main__":
    main()
