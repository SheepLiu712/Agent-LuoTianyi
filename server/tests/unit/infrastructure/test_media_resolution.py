"""MediaResolver 端口与缺省实现的稳定失败契约。"""
import json
from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image

import src.domain.agent as d
from src.infrastructure.media import (
    FilesystemMediaResolver,
    MediaResolutionError,
    MediaResolutionErrorCode,
    UnconfiguredMediaResolver,
)


class _Backend:
    def __init__(self, config, *args, **kwargs):
        self.config = config

    def create_llm_module(self, llm_service):
        self.llm_service = llm_service

    def create_vlm_module(self, llm_service):
        self.llm_service = llm_service

    def wire_dependencies(self, **kwargs):
        self.dependencies = kwargs

    def ensure_dependencies(self):
        return None


def png_bytes():
    image = BytesIO()
    Image.new("RGB", (1, 1)).save(image, format="PNG")
    return image.getvalue()


def test_unconfigured_resolver_fails_explicitly():
    resolver = UnconfiguredMediaResolver()

    with pytest.raises(MediaResolutionError) as caught:
        resolver.resolve(d.MediaRef(media_id="image"), owner_user_id="owner")

    assert caught.value.code == "MEDIA_RESOLVER_NOT_CONFIGURED"
    assert caught.value.media_id == "image"


def test_unconfigured_resolver_dependencies_are_a_noop():
    resolver = UnconfiguredMediaResolver()

    resolver.ensure_dependencies()


def test_infrastructure_runtime_exposes_configured_media_resolver(monkeypatch):
    from src.infrastructure import runtime as module

    for name in ("SpeechBackend", "SingingBackend", "ImageUnderstanding"):
        monkeypatch.setattr(module, name, _Backend)
    manager = module.InfrastructureRuntime(
        {"media_resolution": {"adapter": "unconfigured"}}, object())

    assert isinstance(manager.media_resolver, UnconfiguredMediaResolver)
    manager.media_resolver.ensure_dependencies()


def test_filesystem_resolver_reads_permanent_media(tmp_path):
    media_id = str(uuid4())
    media_dir = tmp_path / media_id
    media_dir.mkdir()
    image = png_bytes()
    (media_dir / "content.bin").write_bytes(image)
    (media_dir / "metadata.json").write_text(
        json.dumps({"mime_type": "image/png", "owner_user_id": "owner"}), encoding="utf-8")

    resolved = FilesystemMediaResolver({"root": str(tmp_path)}).resolve(
        d.MediaRef(media_id=media_id), owner_user_id="owner")

    assert resolved.data == image
    assert resolved.mime_type == "image/png"


@pytest.mark.parametrize(("media_id", "setup", "code"), [
    (str(uuid4()), None, MediaResolutionErrorCode.UNKNOWN),
    (str(uuid4()), (b"", "image/png"), MediaResolutionErrorCode.EMPTY),
    (str(uuid4()), (b"data", "text/plain"), MediaResolutionErrorCode.UNSUPPORTED_TYPE),
    ("../escape", None, MediaResolutionErrorCode.UNKNOWN),
])
def test_filesystem_resolver_rejects_invalid_media(tmp_path, media_id, setup, code):
    if setup is not None:
        media_dir = tmp_path / media_id
        media_dir.mkdir()
        data, mime_type = setup
        (media_dir / "content.bin").write_bytes(data)
        (media_dir / "metadata.json").write_text(json.dumps({
            "mime_type": mime_type, "owner_user_id": "owner",
        }), encoding="utf-8")
    resolver = FilesystemMediaResolver({"root": str(tmp_path)})

    with pytest.raises(MediaResolutionError) as caught:
        resolver.resolve(d.MediaRef(media_id=media_id), owner_user_id="owner")

    assert caught.value.code is code


def test_infrastructure_runtime_builds_filesystem_resolver(monkeypatch, tmp_path):
    from src.infrastructure import runtime as module

    for name in ("SpeechBackend", "SingingBackend", "ImageUnderstanding"):
        monkeypatch.setattr(module, name, _Backend)
    manager = module.InfrastructureRuntime(
        {"media_resolution": {"root": str(tmp_path)}}, object())

    assert isinstance(manager.media_resolver, FilesystemMediaResolver)


def test_filesystem_resolver_rejects_cross_user_before_returning_bytes(tmp_path):
    media_id = str(uuid4())
    media_dir = tmp_path / media_id
    media_dir.mkdir()
    (media_dir / "content.bin").write_bytes(b"secret")
    (media_dir / "metadata.json").write_text(json.dumps({
        "mime_type": "image/png", "owner_user_id": "alice",
    }), encoding="utf-8")

    with pytest.raises(MediaResolutionError) as caught:
        FilesystemMediaResolver({"root": str(tmp_path)}).resolve(
            d.MediaRef(media_id=media_id), owner_user_id="bob")

    assert caught.value.code is MediaResolutionErrorCode.UNAUTHORIZED


def test_filesystem_resolver_treats_incomplete_directory_as_unknown(tmp_path):
    media_id = str(uuid4())
    media_dir = tmp_path / media_id
    media_dir.mkdir()
    (media_dir / "content.bin").write_bytes(b"partial")

    with pytest.raises(MediaResolutionError) as caught:
        FilesystemMediaResolver({"root": str(tmp_path)}).resolve(
            d.MediaRef(media_id=media_id), owner_user_id="owner")

    assert caught.value.code is MediaResolutionErrorCode.UNKNOWN


def test_filesystem_resolver_treats_missing_owner_as_unknown(tmp_path):
    media_id = str(uuid4())
    media_dir = tmp_path / media_id
    media_dir.mkdir()
    (media_dir / "content.bin").write_bytes(png_bytes())
    (media_dir / "metadata.json").write_text(
        json.dumps({"mime_type": "image/png"}), encoding="utf-8")

    with pytest.raises(MediaResolutionError) as caught:
        FilesystemMediaResolver({"root": str(tmp_path)}).resolve(
            d.MediaRef(media_id=media_id), owner_user_id="owner")

    assert caught.value.code is MediaResolutionErrorCode.UNKNOWN


def test_filesystem_resolver_rejects_invalid_declared_image_content(tmp_path):
    media_id = str(uuid4())
    media_dir = tmp_path / media_id
    media_dir.mkdir()
    (media_dir / "content.bin").write_bytes(b"not an image")
    (media_dir / "metadata.json").write_text(json.dumps({
        "mime_type": "image/png", "owner_user_id": "owner",
    }), encoding="utf-8")

    with pytest.raises(MediaResolutionError) as caught:
        FilesystemMediaResolver({"root": str(tmp_path)}).resolve(
            d.MediaRef(media_id=media_id), owner_user_id="owner")

    assert caught.value.code is MediaResolutionErrorCode.UNKNOWN
