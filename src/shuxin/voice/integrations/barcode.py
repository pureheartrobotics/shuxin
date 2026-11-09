from __future__ import annotations

import base64
import binascii
import io
from pathlib import Path
from typing import Any

from PIL import Image


CODE128_PATTERNS = [
    "212222", "222122", "222221", "121223", "121322", "131222", "122213",
    "122312", "132212", "221213", "221312", "231212", "112232", "122132",
    "122231", "113222", "123122", "123221", "223211", "221132", "221231",
    "213212", "223112", "312131", "311222", "321122", "321221", "312212",
    "322112", "322211", "212123", "212321", "232121", "111323", "131123",
    "131321", "112313", "132113", "132311", "211313", "231113", "231311",
    "112133", "112331", "132131", "113123", "113321", "133121", "313121",
    "211331", "231131", "213113", "213311", "213131", "311123", "311321",
    "331121", "312113", "312311", "332111", "314111", "221411", "431111",
    "111224", "111422", "121124", "121421", "141122", "141221", "112214",
    "112412", "122114", "122411", "142112", "142211", "241211", "221114",
    "413111", "241112", "134111", "111242", "121142", "121241", "114212",
    "124112", "124211", "411212", "421112", "421211", "212141", "214121",
    "412121", "111143", "111341", "131141", "114113", "114311", "411113",
    "411311", "113141", "114131", "311141", "411131", "211412", "211214",
    "211232", "2331112",
]
CODE128_WIDTHS = [tuple(int(ch) for ch in pattern) for pattern in CODE128_PATTERNS]


def decode_barcode_image(image: bytes | str | Path) -> dict[str, str]:
    image_bytes = _read_image_bytes(image)
    zxing_result = _decode_with_zxing(image_bytes)
    if zxing_result:
        return zxing_result
    return _decode_code128(image_bytes)


def decode_barcode_image_base64(image_base64: str) -> dict[str, str]:
    encoded = str(image_base64 or "").strip()
    if "," in encoded and encoded.lower().startswith("data:"):
        encoded = encoded.split(",", 1)[1]
    if not encoded:
        raise ValueError("image_base64 is required")
    try:
        return decode_barcode_image(base64.b64decode(encoded, validate=True))
    except (binascii.Error, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc) != "image_base64 is required":
            raise
        raise ValueError("image_base64 is invalid") from exc


def generate_code128_png(
    text: str,
    *,
    module_width: int = 4,
    height: int = 180,
    quiet_zone: int = 40,
) -> bytes:
    payload = str(text or "").strip()
    if not payload:
        raise ValueError("barcode text is required")
    codes = _encode_code128_b(payload)
    width_units = sum(sum(CODE128_WIDTHS[code]) for code in codes)
    width = quiet_zone * 2 + width_units * module_width
    image = Image.new("RGB", (width, height), "white")
    x = quiet_zone
    for code in codes:
        black = True
        for units in CODE128_WIDTHS[code]:
            segment_width = units * module_width
            if black:
                for px in range(x, x + segment_width):
                    for py in range(height):
                        image.putpixel((px, py), (0, 0, 0))
            x += segment_width
            black = not black
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _encode_code128_b(text: str) -> list[int]:
    codes = [104]
    for char in text:
        value = ord(char) - 32
        if value < 0 or value > 95:
            raise ValueError("Code128-B text must contain printable ASCII only")
        codes.append(value)
    checksum = (codes[0] + sum(index * code for index, code in enumerate(codes[1:], 1))) % 103
    return [*codes, checksum, 106]


def _read_image_bytes(image: bytes | str | Path) -> bytes:
    if isinstance(image, bytes):
        return image
    return Path(image).read_bytes()


def _decode_with_zxing(image_bytes: bytes) -> dict[str, str] | None:
    try:
        import zxingcpp  # type: ignore
    except ImportError:
        return None

    with Image.open(io.BytesIO(image_bytes)) as image:
        results = zxingcpp.read_barcodes(image.convert("RGB"))
    if not results:
        return None
    first = results[0]
    text = str(getattr(first, "text", "") or "")
    if not text:
        return None
    return {"text": text, "format": _normalize_format(getattr(first, "format", "UNKNOWN"))}


def _decode_code128(image_bytes: bytes) -> dict[str, str]:
    with Image.open(io.BytesIO(image_bytes)) as image:
        gray = image.convert("L")
        row = _pick_barcode_row(gray)
        runs = _scan_runs(gray, row)
    codes = _runs_to_code128_values(runs)
    text = _decode_code128_values(codes)
    return {"text": text, "format": "CODE_128"}


def _pick_barcode_row(image: Image.Image) -> int:
    best: tuple[int, int] | None = None
    max_y = max(1, int(image.height * 0.75))
    for y in range(max_y):
        black = [_is_black(image.getpixel((x, y))) for x in range(image.width)]
        black_count = sum(black)
        if black_count < max(12, image.width // 20):
            continue
        transitions = sum(black[x] != black[x - 1] for x in range(1, image.width))
        if best is None or transitions > best[0]:
            best = (transitions, y)
    if best is None:
        raise ValueError("barcode not found")
    return best[1]


def _scan_runs(image: Image.Image, y: int) -> list[int]:
    values = [_is_black(image.getpixel((x, y))) for x in range(image.width)]
    black_positions = [x for x, value in enumerate(values) if value]
    if not black_positions:
        raise ValueError("barcode not found")
    sequence = values[min(black_positions): max(black_positions) + 1]
    runs: list[int] = []
    current = sequence[0]
    width = 0
    for value in sequence:
        if value == current:
            width += 1
        else:
            runs.append(width)
            current = value
            width = 1
    runs.append(width)
    if not sequence[0]:
        runs = runs[1:]
    if len(runs) < 13:
        raise ValueError("barcode is too short")
    return runs


def _is_black(value: int) -> bool:
    return value < 128


def _runs_to_code128_values(runs: list[int]) -> list[int]:
    codes: list[int] = []
    index = 0
    while index < len(runs):
        remaining = len(runs) - index
        if remaining == 7:
            codes.append(_best_code128_match(runs[index:index + 7], stop=True))
            index += 7
            break
        if remaining < 7:
            raise ValueError("barcode has incomplete Code128 symbol")
        codes.append(_best_code128_match(runs[index:index + 6], stop=False))
        index += 6
    if not codes or codes[-1] != 106:
        raise ValueError("Code128 stop symbol not found")
    return codes


def _best_code128_match(widths: list[int], *, stop: bool) -> int:
    candidates = [(106, CODE128_WIDTHS[106])] if stop else list(enumerate(CODE128_WIDTHS[:106]))
    best_code = -1
    best_error = float("inf")
    total = float(sum(widths))
    for code, pattern in candidates:
        if len(pattern) != len(widths):
            continue
        scale = total / sum(pattern)
        error = sum(abs(width - expected * scale) for width, expected in zip(widths, pattern)) / total
        if error < best_error:
            best_code = code
            best_error = error
    if best_code < 0 or best_error > 0.22:
        raise ValueError("barcode symbol could not be decoded")
    return best_code


def _decode_code128_values(codes: list[int]) -> str:
    if len(codes) < 4:
        raise ValueError("Code128 payload is too short")
    start = codes[0]
    if start == 103:
        code_set = "A"
    elif start == 104:
        code_set = "B"
    elif start == 105:
        code_set = "C"
    else:
        raise ValueError("Code128 start symbol not found")

    checksum = codes[-2]
    expected = (start + sum(index * code for index, code in enumerate(codes[1:-2], 1))) % 103
    if checksum != expected:
        raise ValueError("Code128 checksum mismatch")

    output: list[str] = []
    for code in codes[1:-2]:
        if code == 99:
            code_set = "C"
            continue
        if code == 100:
            code_set = "B"
            continue
        if code == 101:
            code_set = "A"
            continue
        if code >= 96:
            continue
        output.append(_decode_code128_character(code, code_set))
    return "".join(output)


def _decode_code128_character(code: int, code_set: str) -> str:
    if code_set == "C":
        if code > 99:
            raise ValueError("invalid Code128-C value")
        return f"{code:02d}"
    if code_set == "A":
        if code <= 63:
            return chr(code + 32)
        return chr(code - 64)
    return chr(code + 32)


def _normalize_format(value: Any) -> str:
    raw = str(value).upper()
    if "128" in raw:
        return "CODE_128"
    return raw.rsplit(".", 1)[-1]
