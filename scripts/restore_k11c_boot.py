"""Restore KickPi boot partition from boot.img.bak taken before the logo patch."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from install_k11c_boot_brand import adb, adb_out, adb_retry, become_root, wait_for_device

BAK = ROOT / "android-app" / "boot-brand" / "boot.img.bak"


def main() -> None:
    if not BAK.is_file() or BAK.stat().st_size < 8 * 1024 * 1024:
        raise SystemExit(f"missing backup {BAK}")
    print("backup", BAK, BAK.stat().st_size)
    wait_for_device(1800, why="KickPi to restore boot")
    become_root()
    remote = "/data/local/tmp/boot.img.bak"
    adb_retry("push", str(BAK), remote, timeout=180)
    print(adb_out("shell", "ls", "-l", remote))
    write = adb(
        "shell",
        "sh",
        "-c",
        f"dd if={remote} of=/dev/block/by-name/boot bs=1M conv=fsync && sync",
        check=False,
        timeout=180,
    )
    text = ((write.stdout or "") + (write.stderr or "")).strip()
    print(text)
    if "41943040" not in text and "40+" not in text:
        raise SystemExit("restore dd did not write 40MB")
    print("boot restored. rebooting")
    adb("reboot", check=False)


if __name__ == "__main__":
    main()
