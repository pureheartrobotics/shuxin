"""Pack boot.img.bak into an AOSP recovery zip that dd's boot without unzip."""

from __future__ import annotations

import struct
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "android-app" / "boot-brand"
BAK = BRAND / "boot.img.bak"
OUT = BRAND / "chuxin-restore-boot.zip"
BOOT_NAME = "boot.img"
BOOT_SIZE = 41943040
ALIGN = 4096
LOCAL_HEADER = 30


def extra_for_align(header_offset: int, filename: str) -> bytes:
    base = header_offset + LOCAL_HEADER + len(filename.encode("utf-8"))
    # extra layout: id(2) + size(2) + payload
    pad = (ALIGN - ((base + 4) % ALIGN)) % ALIGN
    return struct.pack("<HH", 0x0000, pad) + (b"\x00" * pad)


UPDATE_BINARY = r"""#!/system/bin/sh
OUTFD="${2:-1}"
ZIP="${3}"

ui_print() {
  echo "ui_print $1" > "/proc/self/fd/${OUTFD}"
  echo "ui_print" > "/proc/self/fd/${OUTFD}"
}

ui_print "ChuXin restore original boot"
OFFSET=__OFFSET__
SIZE=__SIZE__
COUNT=$((SIZE / 4096))
SKIP=$((OFFSET / 4096))

TARGET=""
for p in /dev/block/by-name/boot /dev/block/bootdevice/by-name/boot; do
  if [ -e "$p" ]; then TARGET="$p"; break; fi
done
if [ -z "$TARGET" ]; then
  TARGET=$(ls -1 /dev/block/platform/*/by-name/boot 2>/dev/null | head -n 1)
fi
if [ -z "$TARGET" ] || [ ! -e "$TARGET" ]; then
  ui_print "ERROR: boot partition not found"
  exit 1
fi

ui_print "dd boot ${SIZE} -> $TARGET"
if ! dd if="$ZIP" of="$TARGET" bs=4096 skip="$SKIP" count="$COUNT" conv=fsync; then
  ui_print "ERROR: dd failed"
  exit 1
fi
sync
ui_print "OK. Reboot system now."
exit 0
"""


def main() -> None:
    if not BAK.is_file() or BAK.stat().st_size != BOOT_SIZE:
        raise SystemExit(f"bad backup {BAK}")
    boot = BAK.read_bytes()
    extra = extra_for_align(0, BOOT_NAME)
    data_offset = LOCAL_HEADER + len(BOOT_NAME) + len(extra)
    if data_offset % ALIGN:
        raise SystemExit(f"boot data not aligned: {data_offset}")

    script = (
        UPDATE_BINARY.replace("__OFFSET__", str(data_offset))
        .replace("__SIZE__", str(BOOT_SIZE))
        .encode("utf-8")
    )
    OUT.unlink(missing_ok=True)
    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as zf:
        boot_info = zipfile.ZipInfo(BOOT_NAME)
        boot_info.compress_type = zipfile.ZIP_STORED
        boot_info.extra = extra
        boot_info.external_attr = 0o100644 << 16
        zf.writestr(boot_info, boot)

        bin_info = zipfile.ZipInfo("META-INF/com/google/android/update-binary")
        bin_info.compress_type = zipfile.ZIP_DEFLATED
        bin_info.external_attr = 0o100755 << 16
        zf.writestr(bin_info, script)

        us_info = zipfile.ZipInfo("META-INF/com/google/android/updater-script")
        us_info.compress_type = zipfile.ZIP_DEFLATED
        us_info.external_attr = 0o100644 << 16
        zf.writestr(us_info, b'# ChuXin boot restore; work is in update-binary\n')

    with zipfile.ZipFile(OUT) as zf:
        info = zf.getinfo(BOOT_NAME)
        actual = info.header_offset + LOCAL_HEADER + len(info.filename) + len(info.extra)
        if actual != data_offset or info.compress_type != zipfile.ZIP_STORED:
            raise SystemExit(f"zip layout mismatch actual={actual} expected={data_offset}")
    print("wrote", OUT, OUT.stat().st_size, "boot_offset", data_offset)


if __name__ == "__main__":
    main()
