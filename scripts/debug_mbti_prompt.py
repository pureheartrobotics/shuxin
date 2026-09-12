#!/usr/bin/env python3
"""Print MBTI Slot2/Slot4 prompt blocks for side-by-side review."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuxin.core.identity import IdentityEngine, load_mbti_profiles  # noqa: E402


def _parse_types(raw: str) -> list[str]:
    return [part.strip().upper() for part in raw.split(",") if part.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Debug MBTI prompt injection blocks.")
    parser.add_argument(
        "--types",
        default="INFJ,ENFP,ISTJ",
        help="Comma-separated MBTI types (default: INFJ,ENFP,ISTJ)",
    )
    args = parser.parse_args()
    types = _parse_types(args.types)

    profiles = load_mbti_profiles()
    missing = [mbti for mbti in types if mbti not in profiles]
    if missing:
        print(f"Unknown types: {', '.join(missing)}", file=sys.stderr)
        return 1

    slot2_blocks: dict[str, str] = {}
    micro_anchors: dict[str, str] = {}

    for mbti in types:
        engine = IdentityEngine(mbti)
        entry = profiles[mbti]
        slot2 = engine.get_system_prompt_block()
        micro = engine.get_micro_anchor()
        slot2_blocks[mbti] = slot2
        micro_anchors[mbti] = micro

        print("=" * 72)
        print(f"[{mbti}] {entry.get('tagline', '')}")
        print("-" * 72)
        print("Slot2 (style_anchor):")
        print(slot2)
        print()
        print("Slot4 (micro_anchor):")
        print(micro)
        print()
        print("reveal_script:")
        print(str(entry.get("reveal_script") or "").strip())
        print()

    print("=" * 72)
    print("Summary")
    print("-" * 72)
    for mbti in types:
        print(f"{mbti}: Slot2={len(slot2_blocks[mbti])} chars, micro={len(micro_anchors[mbti])} chars")

    slot2_unique = len(set(slot2_blocks.values())) == len(types)
    micro_unique = len(set(micro_anchors.values())) == len(types)
    print(f"Slot2 all distinct: {slot2_unique}")
    print(f"micro_anchor all distinct: {micro_unique}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
