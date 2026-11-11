"""Replace Rockchip 654x270 RLE8 logos inside KickPi boot.img."""

from __future__ import annotations

import io
import struct
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "android-app" / "boot-brand"
LOGO_JPG = ROOT / "android-app" / "app" / "src" / "main" / "res" / "drawable" / "boot_logo.jpg"
SLOTS = ((39197184, 12936), (39210496, 22364))


def rle8_row(pixels: bytes) -> bytes:
    out = bytearray()
    i = 0
    n = len(pixels)
    while i < n:
        val = pixels[i]
        j = i + 1
        while j < n and pixels[j] == val and (j - i) < 255:
            j += 1
        out += bytes((j - i, val))
        i = j
    out += b"\x00\x00"
    return bytes(out)


def encode_rle8_bmp(im: Image.Image) -> bytes:
    im = im.convert("P", palette=Image.Palette.ADAPTIVE, colors=256)
    width, height = im.size
    palette = im.getpalette() or []
    pal = bytearray(1024)
    for index in range(256):
        if index * 3 + 2 < len(palette):
            red, green, blue = palette[index * 3 : index * 3 + 3]
            pal[index * 4 : index * 4 + 4] = bytes((blue, green, red, 0))
    body = bytearray()
    for y in range(height - 1, -1, -1):
        row = bytes(im.crop((0, y, width, y + 1)).getdata())
        body += rle8_row(row)
    body += b"\x00\x01"
    pixel_off = 54 + 1024
    size = pixel_off + len(body)
    header = struct.pack(
        "<2sIHHIIiiHHIIiiII",
        b"BM",
        size,
        0,
        0,
        pixel_off,
        40,
        width,
        height,
        1,
        8,
        1,
        len(body),
        2835,
        2835,
        256,
        256,
    )
    return header + bytes(pal) + bytes(body)


def compose(width: int, height: int, use_brand: bool) -> Image.Image:
    canvas = Image.new("RGB", (width, height), (0, 0, 0))
    if not use_brand:
        return canvas
    logo = Image.open(LOGO_JPG).convert("RGB")
    fitted = ImageOps.contain(logo, (width, height), Image.Resampling.LANCZOS)
    canvas.paste(fitted, ((width - fitted.width) // 2, (height - fitted.height) // 2))
    return canvas


def main() -> None:
    black = encode_rle8_bmp(compose(654, 270, False))
    brand = encode_rle8_bmp(compose(654, 270, True))
    print("black", len(black), "brand", len(brand))
    (BRAND / "rle_black.bmp").write_bytes(black)
    (BRAND / "rle_brand.bmp").write_bytes(brand)
    Image.open(io.BytesIO(black)).save(BRAND / "rle_black.png")
    Image.open(io.BytesIO(brand)).save(BRAND / "rle_brand.png")

    src = BRAND / "boot.img.new"
    if not src.is_file():
        src = BRAND / "boot.img.bak"
    blob = bytearray(src.read_bytes())
    for pos, cap in SLOTS:
        payload = brand if len(brand) <= cap else black
        if len(payload) > cap:
            raise SystemExit(f"payload {len(payload)} > slot {cap}")
        blob[pos : pos + len(payload)] = payload
        if len(payload) < cap:
            blob[pos + len(payload) : pos + cap] = b"\x00" * (cap - len(payload))
        print("slot", pos, "used", len(payload), "cap", cap, "kind", "brand" if payload is brand else "black")
    out = BRAND / "boot.img.new"
    out.write_bytes(blob)
    print("wrote", out, len(blob), "logo.nologo", b"logo.nologo" in bytes(blob[:4096]))


if __name__ == "__main__":
    main()
