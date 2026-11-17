import base64
from io import BytesIO
from pathlib import Path

from PIL import Image
from src.utils import image_compression, image_encoding, image_rules


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


def test_oversized_bmp_is_sent_as_jpeg_without_changing_original(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "large.bmp"
    Image.new("RGB", (3000, 1000), "red").save(path)
    original = path.read_bytes()
    assert len(original) > image_rules.MAX_IMAGE_BYTES
    result = image_encoding.prepare_image_payload(str(path))
    assert result["ok"]
    data = base64.b64decode(result["image_base64"])
    assert len(data) <= image_compression.IMAGE_COMPRESSION_TARGET_BYTES
    assert result["mime_type"] == "image/jpeg"
    assert Path(result["image_client_path"]).suffix == ".jpg"
    assert Path(result["image_client_path"]).read_bytes() == data
    with Image.open(BytesIO(data)) as image:
        assert image.format == "JPEG"
        assert image.width == 2560
    assert path.read_bytes() == original


def test_png_compression_preserves_alpha(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "transparent.png"
    Image.new("RGBA", (40, 20), (255, 0, 0, 64)).save(path)
    with path.open("ab") as file:
        file.write(b"\0" * image_rules.MAX_IMAGE_BYTES)
    result = image_encoding.prepare_image_payload(str(path))
    assert result["ok"] and result["mime_type"] == "image/png"
    with Image.open(result["image_client_path"]) as image:
        assert image.size == (40, 20)
        assert image.getpixel((0, 0))[3] == 64


def test_size_lookup_failure_still_reads_original(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"original")
    monkeypatch.setattr(image_rules, "MAX_IMAGE_BYTES", 3)

    def fail_stat(_):
        raise OSError("metadata unavailable")

    monkeypatch.setattr(image_encoding.os.path, "getsize", fail_stat)
    result = image_encoding.prepare_image_payload(str(path))
    assert result["ok"]
    assert base64.b64decode(result["image_base64"]) == b"original"


def test_exact_limit_preserves_original_without_compression(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"original")
    monkeypatch.setattr(image_rules, "MAX_IMAGE_BYTES", 8)
    result = image_encoding.prepare_image_payload(str(path))
    assert result["ok"]
    assert base64.b64decode(result["image_base64"]) == b"original"


def test_unreadable_image_reports_chinese_error(tmp_path):
    result = image_encoding.prepare_image_payload(str(tmp_path / "missing.jpg"))
    assert not result["ok"] and result["drop"]
    assert "图片无法读取" in result["error"]


def test_temp_images_do_not_overwrite_each_other(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"one")
    first = image_encoding.prepare_image_payload(str(path))
    path.write_bytes(b"two")
    second = image_encoding.prepare_image_payload(str(path))
    assert first["image_client_path"] != second["image_client_path"]
    assert Path(first["image_client_path"]).read_bytes() == b"one"


def test_compression_second_stage_and_exhaustion(monkeypatch):
    import pytest

    source = BytesIO()
    Image.new("RGB", (3000, 1000), "red").save(source, format="BMP")
    monkeypatch.setattr(image_compression, "IMAGE_COMPRESSION_TARGET_BYTES", 30000)
    data, mime, suffix = image_compression.compress_image_for_upload(source.getvalue(), "image/bmp")
    with Image.open(BytesIO(data)) as image:
        assert image.width == 2048
    assert mime == "image/jpeg" and suffix == ".jpg"
    monkeypatch.setattr(image_compression, "IMAGE_COMPRESSION_TARGET_BYTES", 1)
    with pytest.raises(ValueError, match="remains too large"):
        image_compression.compress_image_for_upload(source.getvalue(), "image/bmp")
