from pathlib import Path

from src.utils import image_encoding, image_rules


def test_prepare_image_payload_rejects_unknown_extension(tmp_path):
    image_path = tmp_path / "image.svg"
    image_path.write_text("<svg/>", encoding="utf-8")

    result = image_encoding.prepare_image_payload(str(image_path))

    assert result == {
        "ok": False,
        "error": "不支持的图片格式，请选择 JPG、PNG、GIF、BMP 或 WebP 图片",
        "drop": True,
    }


def test_prepare_image_payload_rejects_oversized_file(tmp_path, monkeypatch):
    monkeypatch.setattr(image_rules, "MAX_IMAGE_BYTES", 3)
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"1234")

    result = image_encoding.prepare_image_payload(str(image_path))

    assert result == {
        "ok": False,
        "error": "图片过大（上限约 6 MB），请选择更小的图片",
        "drop": True,
    }


def test_prepare_image_payload_uses_validated_mime(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    image_path = tmp_path / "image.JPEG"
    image_path.write_bytes(b"image")

    result = image_encoding.prepare_image_payload(str(image_path))

    assert result["ok"] is True
    assert result["mime_type"] == "image/jpeg"
    assert Path(result["image_client_path"]).read_bytes() == b"image"
