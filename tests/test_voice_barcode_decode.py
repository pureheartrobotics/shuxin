from __future__ import annotations

import base64
from pathlib import Path

from fastapi.testclient import TestClient

from shuxin.voice.barcode import decode_barcode_image, generate_code128_png
from shuxin.voice.server import create_app


FIXTURE = Path("data/pic/test.png")


def test_decode_barcode_fixture_image() -> None:
    result = decode_barcode_image(FIXTURE.read_bytes())

    assert result["text"] == "1234567890ABC"
    assert result["format"] == "CODE_128"


def test_barcode_decode_api_accepts_base64_image() -> None:
    app = create_app()
    image_base64 = base64.b64encode(FIXTURE.read_bytes()).decode("ascii")

    with TestClient(app) as client:
        response = client.post("/api/barcodes/decode", json={"image_base64": image_base64})

    assert response.status_code == 200
    assert response.json()["text"] == "1234567890ABC"


def test_generated_code128_png_can_be_decoded() -> None:
    image = generate_code128_png("CLM-A001-000123")
    result = decode_barcode_image(image)

    assert result == {"text": "CLM-A001-000123", "format": "CODE_128"}
