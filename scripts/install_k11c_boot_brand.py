"""Replace KickPi K11C Rockchip/Android boot screens with the 初心 splash.

1) Android bootanimation -> 稚子心 logo looping until the app starts
2) Rockchip logo/resource partition BMPs -> same splash (backup first)
"""

from __future__ import annotations

import io
import os
import struct
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
LOGO_JPG = ROOT / "android-app" / "app" / "src" / "main" / "res" / "drawable" / "boot_logo.jpg"
OUT_DIR = ROOT / "android-app" / "boot-brand"
ADB_CANDIDATES = [
    ROOT / ".android-sdk" / "platform-tools" / "adb.exe",
    ROOT / "RKDevTool_v3.30_for_window" / "RKDevTool_v3.30_for_window" / "bin" / "adb.exe",
]
COMMON_SIZES = ((1280, 800), (1920, 1080), (800, 1280), (1024, 600), (1920, 1200))


def adb_bin() -> str:
    for path in ADB_CANDIDATES:
        if path.is_file():
            return str(path)
    return "adb"


def adb(*args: str, check: bool = True, timeout: int = 40) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            [adb_bin(), *args],
            check=check,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        print(f"adb timeout: {' '.join(args)}")
        if check:
            raise
        stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return subprocess.CompletedProcess(exc.cmd, 1, stdout, stderr)


def adb_out(*args: str) -> str:
    proc = adb(*args, check=False)
    return ((proc.stdout or "") + (proc.stderr or "")).strip()


def adb_retry(*args: str, attempts: int = 6, timeout: int = 60) -> subprocess.CompletedProcess:
    last = subprocess.CompletedProcess(list(args), 1, "", "")
    for i in range(1, attempts + 1):
        wait_for_device(180, why=f"adb {args[0]}")
        last = adb(*args, check=False, timeout=timeout)
        if last.returncode == 0:
            return last
        err = ((last.stderr or "") + (last.stdout or "")).strip().replace("\r", "")
        print(f"adb {args[0]} failed ({i}/{attempts}) {err[:400]}", flush=True)
        time.sleep(2)
    raise SystemExit(f"adb failed: {' '.join(args)}\n{((last.stderr or '') + (last.stdout or '')).strip()}")


def wait_for_device(seconds: int = 900, why: str = "KickPi over USB") -> None:
    print(f"waiting for {why}...", flush=True)
    deadline = time.time() + seconds
    last = ""
    while time.time() < deadline:
        proc = adb("devices", check=False, timeout=8)
        text = (proc.stdout or "") + (proc.stderr or "")
        lines = [
            line
            for line in text.splitlines()
            if "List" not in line
            and any(tag in line for tag in ("\tdevice", "\trecovery", "\tsideload", "\tbootloader"))
        ]
        if lines:
            print("device", lines[0].split()[0], flush=True)
            return
        if text != last and text.strip():
            print(text.strip(), flush=True)
            last = text
        time.sleep(2)
    raise SystemExit("board not on USB. plug K11C Type-C (OTG) with a data cable and retry.")


def load_logo() -> Image.Image:
    return Image.open(LOGO_JPG).convert("RGB")


def compose_splash(logo: Image.Image, width: int, height: int) -> Image.Image:
    canvas = Image.new("RGB", (width, height), (0, 0, 0))
    fitted = ImageOps.contain(logo, (width, height), Image.Resampling.LANCZOS)
    x = (width - fitted.width) // 2
    y = (height - fitted.height) // 2
    canvas.paste(fitted, (x, y))
    return canvas


def splash_bmp_bytes(logo: Image.Image, width: int, height: int) -> bytes:
    image = compose_splash(logo, width, height)
    buf = io.BytesIO()
    image.save(buf, format="BMP")
    return buf.getvalue()


def write_bootanimation(logo: Image.Image, width: int, height: int) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    png = compose_splash(logo, width, height)
    zip_path = OUT_DIR / "bootanimation.zip"
    with tempfile.TemporaryDirectory() as tmp:
        part = Path(tmp) / "part0"
        part.mkdir()
        png.save(part / "00000.png", format="PNG")
        desc = Path(tmp) / "desc.txt"
        desc.write_text(f"{width} {height} 15\np 0 0 part0\n", encoding="ascii")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
            zf.write(desc, "desc.txt")
            zf.write(part / "00000.png", "part0/00000.png")
    return zip_path


def parse_rsce(blob: bytes) -> list[tuple[str, int, int]]:
    if blob[:4] != b"RSCE":
        return []
    try:
        _magic, _pv, _iv, header_size, tbl_offset, tbl_entry_size, tbl_entry_num = struct.unpack_from(
            "<4sHHBBBI", blob, 0
        )
    except struct.error:
        return []
    block = 512
    header_bytes = max(int(header_size), 1) * block
    table_at = int(tbl_offset) * block
    entry_size = int(tbl_entry_size) * block if int(tbl_entry_size) <= 8 else int(tbl_entry_size)
    if entry_size < 64 or tbl_entry_num > 64:
        entry_size, table_at, tbl_entry_num = 512, 512, min(int(tbl_entry_num) or 8, 32)
    entries: list[tuple[str, int, int]] = []
    for index in range(int(tbl_entry_num) or 8):
        off = table_at + index * entry_size
        if off + 232 > len(blob):
            break
        tag = blob[off : off + 4]
        if tag not in (b"ENTR", b"RSCE") and blob[off + 4 : off + 8] == b"\x00\x00\x00\x00":
            continue
        name = blob[off + 4 : off + 224].split(b"\x00", 1)[0].decode("ascii", "ignore").strip()
        if not name:
            name = blob[off : off + 220].split(b"\x00", 1)[0].decode("ascii", "ignore").strip()
            f_offset, f_size = struct.unpack_from("<II", blob, off + 220)
        else:
            f_offset, f_size = struct.unpack_from("<II", blob, off + 224)
        if not name or f_size == 0 or f_offset + f_size > len(blob) + block * 8:
            continue
        if name.lower().endswith((".bmp", ".jpg", ".png")) or "logo" in name.lower():
            entries.append((name, f_offset, f_size))
    return entries


def find_bmp_slots(blob: bytes) -> list[tuple[int, int, int, int]]:
    slots = []
    start = 0
    while True:
        pos = blob.find(b"BM", start)
        if pos < 0:
            break
        if pos + 26 > len(blob):
            break
        size, _, _, _, bpp = struct.unpack_from("<IIIHH", blob, pos + 2)
        width, height = struct.unpack_from("<ii", blob, pos + 18)
        height = abs(height)
        if 8 <= width <= 4096 and 8 <= height <= 4096 and 54 <= size <= len(blob) - pos:
            slots.append((pos, size, width, height))
            start = pos + max(size, 2)
        else:
            start = pos + 2
    return slots


def patch_logo_blob(blob: bytes, logo: Image.Image) -> bytes | None:
    patched = bytearray(blob)
    changed = False
    entries = parse_rsce(blob)
    for name, offset, size in entries:
        width, height = None, None
        if offset + 26 <= len(blob) and blob[offset : offset + 2] == b"BM":
            width, height = struct.unpack_from("<ii", blob, offset + 18)
            height = abs(height)
        if not width:
            continue
        data = splash_bmp_bytes(logo, width, height)
        if len(data) > size:
            print(f"skip {name}: new bmp {len(data)} > slot {size}")
            continue
        patched[offset : offset + len(data)] = data
        if len(data) < size:
            patched[offset + len(data) : offset + size] = b"\x00" * (size - len(data))
        print(f"patched RSCE {name} {width}x{height}")
        changed = True
    if changed:
        return bytes(patched)
    for pos, size, width, height in find_bmp_slots(blob):
        data = splash_bmp_bytes(logo, width, height)
        if len(data) > size:
            print(f"skip BMP@{pos}: {len(data)} > {size}")
            continue
        patched[pos : pos + len(data)] = data
        if len(data) < size:
            patched[pos + len(data) : pos + size] = b"\x00" * (size - len(data))
        print(f"patched BMP {width}x{height} at {pos}")
        changed = True
    return bytes(patched) if changed else None


def become_root() -> None:
    for i in range(1, 6):
        who = adb_out("shell", "id")
        if "uid=0" in who:
            print("already root")
            break
        print(f"adb root ({i}/5); USB may drop")
        adb("root", check=False, timeout=8)
        time.sleep(4)
        wait_for_device(90, why="adb after root")
        who = adb_out("shell", "id")
        print(who)
        if "uid=0" in who:
            break
    remount = adb("remount", check=False, timeout=20)
    text = ((remount.stdout or "") + (remount.stderr or "")).strip()
    print(text[:300] if text else "remount: no output", flush=True)
    if "uid=0" not in adb_out("shell", "id"):
        raise SystemExit("adb root did not stick; cannot write /system")


def screen_size() -> tuple[int, int]:
    text = adb_out("shell", "wm", "size")
    for token in text.replace("Physical", " ").replace("size:", " ").split():
        if "x" not in token:
            continue
        left, _, right = token.partition("x")
        if left.isdigit() and right.isdigit():
            width, height = int(left), int(right)
            if width < height:
                width, height = height, width
            return width, height
    return 1280, 800


def push_bootanimation(zip_path: Path) -> None:
    targets = [
        "/system/media/bootanimation.zip",
        "/system/product/media/bootanimation.zip",
        "/product/media/bootanimation.zip",
        "/oem/media/bootanimation.zip",
        "/vendor/media/bootanimation.zip",
    ]
    existing = adb_out(
        "shell",
        "sh",
        "-c",
        "ls /system/media/bootanimation.zip /product/media/bootanimation.zip /vendor/media/bootanimation.zip /oem/media/bootanimation.zip 2>/dev/null",
    )
    dests = [line.strip() for line in existing.splitlines() if line.strip().endswith(".zip")]
    if not dests:
        dests = [targets[0]]
    remote = "/data/local/tmp/bootanimation.zip"
    adb_retry("push", str(zip_path), remote, timeout=60)
    dests = list(dict.fromkeys(dests + ["/system/media/bootanimation.zip", "/product/media/bootanimation.zip"]))
    for dest in dests:
        print("install bootanimation ->", dest)
        folder = dest.rsplit("/", 1)[0]
        adb_retry(
            "shell",
            "sh",
            "-c",
            f"mkdir -p {folder} && cp {remote} {dest} && chmod 644 {dest} && ls -l {dest}",
            timeout=40,
        )


def patch_logo_partitions(logo: Image.Image) -> None:
    names = adb_out("shell", "ls", "/dev/block/by-name")
    wanted = [name for name in names.split() if name.lower() in {"logo", "resource", "uboot_logo", "boot_logo"}]
    if not wanted:
        print("no logo/resource partition names visible")
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name in wanted:
        remote = f"/dev/block/by-name/{name}"
        tmp = f"/data/local/tmp/{name}.img"
        local = OUT_DIR / f"{name}.img.bak"
        print("dump", remote)
        adb("shell", "dd", f"if={remote}", f"of={tmp}", "bs=4096", check=False, timeout=60)
        pull = adb("pull", tmp, str(local), check=False, timeout=60)
        if not local.is_file() or local.stat().st_size < 64:
            print("skip", name, (pull.stderr or "").strip())
            continue
        blob = local.read_bytes()
        patched = patch_logo_blob(blob, logo)
        if not patched:
            print(name, "has no replaceable BMP; left untouched")
            continue
        patched_path = OUT_DIR / f"{name}.img.new"
        patched_path.write_bytes(patched)
        adb_retry("push", str(patched_path), tmp, timeout=60)
        write = adb(
            "shell",
            "dd",
            f"if={tmp}",
            f"of={remote}",
            "bs=4096",
            "conv=fsync",
            check=False,
            timeout=60,
        )
        print("wrote", name, (write.stdout or write.stderr or "").strip())


def _insert_cmdline_token(raw: bytes, token: str = "logo.nologo") -> bytes | None:
    text = raw.split(b"\x00", 1)[0].decode("ascii", "replace")
    if token in text.split():
        print("cmdline already has", token)
        return None
    extra = (" " + token).encode("ascii")
    used = len(text.encode("ascii"))
    if used + len(extra) + 1 >= len(raw):
        print("cmdline has no room for", token)
        return None
    out = bytearray(raw)
    out[used : used + len(extra)] = extra
    print("cmdline +", token)
    return bytes(out)


def patch_boot_cmdline(blob: bytes) -> bytes | None:
    patched = bytearray(blob)
    changed = False
    if blob.startswith(b"ANDROID!"):
        header_version = struct.unpack_from("<I", blob, 40)[0]
        print("ANDROID boot header_version", header_version)
        if header_version <= 2:
            for offset, size in ((64, 512), (608, 1024)):
                updated = _insert_cmdline_token(bytes(patched[offset : offset + size]))
                if updated:
                    patched[offset : offset + size] = updated
                    changed = True
        else:
            print("boot v3+ has no cmdline; will try vendor_boot")
    elif blob.startswith(b"VNDRBOOT"):
        header_version = struct.unpack_from("<I", blob, 8)[0]
        print("VNDRBOOT header_version", header_version)
        updated = _insert_cmdline_token(bytes(patched[28 : 28 + 2048]))
        if updated:
            patched[28 : 28 + 2048] = updated
            changed = True
    else:
        print("not an Android/vendor boot image")
        return None
    return bytes(patched) if changed else None


def dump_partition(name: str) -> Path | None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    remote = f"/dev/block/by-name/{name}"
    tmp = f"/data/local/tmp/{name}.img"
    local = OUT_DIR / f"{name}.img.bak"
    print("dump", remote)
    adb(
        "shell",
        "sh",
        "-c",
        f"dd if={remote} of={tmp} bs=4M conv=fsync",
        check=False,
        timeout=180,
    )
    pull = adb("pull", tmp, str(local), check=False, timeout=180)
    if not local.is_file() or local.stat().st_size < 64:
        print("skip", name, (pull.stderr or "").strip())
        return None
    print(name, "bytes", local.stat().st_size)
    return local


def write_partition(name: str, data: bytes, original_size: int) -> None:
    if len(data) > original_size:
        raise SystemExit(f"{name} patched image larger than partition")
    if len(data) < original_size:
        data = data + b"\x00" * (original_size - len(data))
    patched_path = OUT_DIR / f"{name}.img.new"
    patched_path.write_bytes(data)
    tmp = f"/data/local/tmp/{name}.img.new"
    adb_retry("push", str(patched_path), tmp, timeout=180)
    listed = adb_out("shell", "ls", "-l", tmp)
    print("remote", listed)
    if str(original_size) not in listed:
        raise SystemExit(f"push of {name} did not land ({listed})")
    write = adb(
        "shell",
        "sh",
        "-c",
        f"dd if={tmp} of=/dev/block/by-name/{name} bs=1M conv=fsync && sync",
        check=False,
        timeout=180,
    )
    text = ((write.stdout or "") + (write.stderr or "")).strip()
    print("wrote", name, text[:300])
    if "0 bytes" in text or "0+0" in text:
        raise SystemExit(f"dd wrote nothing to {name}: {text}")


def patch_kernel_logo(logo: Image.Image) -> None:
    names = set(adb_out("shell", "ls", "/dev/block/by-name").split())
    print("verifiedboot", adb_out("shell", "getprop", "ro.boot.verifiedbootstate"))
    print("cmdline", adb_out("shell", "cat", "/proc/cmdline")[:400])
    targets = [name for name in ("boot", "vendor_boot", "init_boot", "uboot") if name in names]
    if not targets:
        print("no boot/uboot partitions")
        return
    for name in targets:
        local = dump_partition(name)
        if not local:
            continue
        blob = local.read_bytes()
        original_size = len(blob)
        working = blob
        cmd = patch_boot_cmdline(working)
        if cmd:
            working = cmd
        bmp = patch_logo_blob(working, logo)
        if bmp:
            working = bmp
        if working is blob:
            print(name, "unchanged")
            continue
        write_partition(name, working, original_size)


def main() -> None:
    kernel_only = "--kernel-logo-only" in sys.argv
    if not LOGO_JPG.is_file():
        raise SystemExit(f"missing {LOGO_JPG}")
    wait_for_device()
    become_root()
    logo = load_logo()
    if not kernel_only:
        apk = ROOT / "android-app" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
        if apk.is_file():
            print("install", apk.name)
            adb("install", "-r", "-g", str(apk), timeout=120, check=False)
            adb("shell", "cmd", "package", "set-home-activity", "cn.shuxin.car/.MainActivity", check=False)
            adb("reverse", "tcp:8765", "tcp:8765", check=False)
        width, height = screen_size()
        print("panel", width, height)
        zip_path = write_bootanimation(logo, width, height)
        print("bootanimation", zip_path, zip_path.stat().st_size)
        push_bootanimation(zip_path)
        patch_logo_partitions(logo)
        adb(
            "shell",
            "sh",
            "-c",
            "setprop persist.sys.nobootanimation 0; setprop persist.sys.disable_rescue true; settings put global hide_error_dialogs 1",
            check=False,
        )
    patch_kernel_logo(logo)
    print("done. reboot; Rockchip kernel splash should be gone or replaced.")
    print("rebooting in 2s")
    time.sleep(2)
    adb("reboot", check=False)


if __name__ == "__main__":
    main()
