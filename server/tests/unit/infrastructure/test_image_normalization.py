"""MPO 主图规范化与持久化契约。"""

import json
from hashlib import sha256
from io import BytesIO

import pytest
from PIL import Image

from src.infrastructure.media import FilesystemMediaResolver
from src.infrastructure.media.image_validation import prepare_image_content
from src.infrastructure.media.media_resolver import MediaResolutionError
from src.infrastructure.media.media_store import PermanentMediaStore


def mpo_bytes():
    output = BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (16, 24), "red").save(
        output,
        format="MPO",
        save_all=True,
        append_images=[Image.new("RGB", (8, 12), "blue")],
        exif=exif,
    )
    return output.getvalue()


def test_mpo_persistence_resolves_primary_jpeg_and_replays(tmp_path):
    store = PermanentMediaStore({"root": str(tmp_path)})
    ref = store.mint_ref(user_id="owner", client_msg_id="mpo")
    original = mpo_bytes()
    for _ in range(2):
        store.persist_image(media_ref=ref, owner_user_id="owner", data=original, mime_type="image/jpeg")
    result = FilesystemMediaResolver({"root": str(tmp_path)}).resolve(ref, owner_user_id="owner")
    assert result.mime_type == "image/jpeg"
    with Image.open(BytesIO(result.data)) as image:
        assert image.format == "JPEG"
        assert image.size == (24, 16)
        assert image.getpixel((0, 0))[0] > 240
        assert not image.getexif().get(274)
    metadata = json.loads((tmp_path / ref.media_id / "metadata.json").read_text())
    assert metadata["byte_length"] == len(result.data)
    assert metadata["sha256"] == sha256(result.data).hexdigest()


@pytest.mark.parametrize("format_name", ["JPEG", "PNG", "WEBP", "GIF", "BMP"])
def test_supported_images_keep_original_bytes(format_name):
    output = BytesIO()
    Image.new("RGB", (8, 8)).save(output, format=format_name)
    data = output.getvalue()
    normalized, _ = prepare_image_content(data, None, "image")
    assert normalized == data


def test_unsupported_and_corrupt_images_still_rejected():
    output = BytesIO()
    Image.new("RGB", (8, 8)).save(output, format="PPM")
    for data, expected in [(output.getvalue(), "MEDIA_UNSUPPORTED_TYPE"), (b"broken", "MEDIA_UNKNOWN")]:
        with pytest.raises(MediaResolutionError) as caught:
            prepare_image_content(data, None, "image")
        assert caught.value.code == expected


def test_normalized_size_limit_before_persistence(tmp_path, monkeypatch):
    from src.infrastructure.media import media_store

    monkeypatch.setattr(media_store, "prepare_image_content", lambda *args: (b"x" * 11, "image/jpeg"))
    store = PermanentMediaStore({"root": str(tmp_path), "max_bytes": 10})
    ref = store.mint_ref(user_id="owner", client_msg_id="oversized")
    with pytest.raises(MediaResolutionError) as caught:
        store.persist_image(media_ref=ref, owner_user_id="owner", data=b"small")
    assert caught.value.code == "MEDIA_TOO_LARGE"
    assert not (tmp_path / ref.media_id).exists()


@pytest.mark.parametrize("format_name", ["TIFF", "GIF", "PNG", "WEBP"])
def test_multiframe_formats_persist_only_primary(tmp_path, format_name):
    output = BytesIO()
    Image.new("RGB", (16, 16), "red").save(
        output, format=format_name, save_all=True, append_images=[Image.new("RGB", (16, 16), "blue")]
    )
    with Image.open(BytesIO(output.getvalue())) as original:
        assert original.n_frames == 2
    store = PermanentMediaStore({"root": str(tmp_path)})
    ref = store.mint_ref(user_id="owner", client_msg_id=format_name)
    store.persist_image(media_ref=ref, owner_user_id="owner", data=output.getvalue())
    result = FilesystemMediaResolver({"root": str(tmp_path)}).resolve(ref, owner_user_id="owner")
    with Image.open(BytesIO(result.data)) as primary:
        assert getattr(primary, "n_frames", 1) == 1
        assert primary.convert("RGB").getpixel((0, 0))[0] > 240


def test_animated_transparency_is_preserved():
    output = BytesIO()
    Image.new("RGBA", (8, 8), (255, 0, 0, 0)).save(
        output, format="PNG", save_all=True, append_images=[Image.new("RGBA", (8, 8), "blue")]
    )
    data, mime = prepare_image_content(output.getvalue(), "image/png", "transparent")
    assert mime == "image/png"
    with Image.open(BytesIO(data)) as primary:
        assert getattr(primary, "n_frames", 1) == 1
        assert primary.getpixel((0, 0))[3] == 0
