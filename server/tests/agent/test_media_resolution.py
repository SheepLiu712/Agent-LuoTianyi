"""MediaResolver 端口与缺省实现的稳定失败契约。"""
import json
from uuid import uuid4

import pytest

import src.domain.agent as d
from src.capabilities.media_resolution import (
    FilesystemMediaResolver,
    MediaResolutionError,
    MediaResolutionErrorCode,
    UnconfiguredMediaResolver,
)


class _Capability:
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


def test_unconfigured_resolver_fails_explicitly():
    resolver = UnconfiguredMediaResolver()

    with pytest.raises(MediaResolutionError) as caught:
        resolver.resolve(d.MediaRef(media_id="image"))

    assert caught.value.code == "MEDIA_RESOLVER_NOT_CONFIGURED"
    assert caught.value.media_id == "image"


def test_unconfigured_resolver_dependencies_are_a_noop():
    resolver = UnconfiguredMediaResolver()

    resolver.ensure_dependencies()


def test_capability_manager_exposes_configured_media_resolver(monkeypatch):
    from src.capabilities import capability_manager as module

    for name in (
        "SpeechCapability", "SingingCapability", "DynamicCapability",
        "DiaryCapability", "ImageUnderstanding",
    ):
        monkeypatch.setattr(module, name, _Capability)
    manager = module.CapabilityManager(
        {"media_resolution": {"adapter": "unconfigured"}}, object())

    assert isinstance(manager.media_resolver, UnconfiguredMediaResolver)
    manager.media_resolver.ensure_dependencies()


def test_filesystem_resolver_reads_permanent_media(tmp_path):
    media_id = str(uuid4())
    media_dir = tmp_path / media_id
    media_dir.mkdir()
    (media_dir / "content.bin").write_bytes(b"image")
    (media_dir / "metadata.json").write_text(
        json.dumps({"mime_type": "image/png"}), encoding="utf-8")

    resolved = FilesystemMediaResolver({"root": str(tmp_path)}).resolve(
        d.MediaRef(media_id=media_id))

    assert resolved.data == b"image"
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
        (media_dir / "metadata.json").write_text(
            json.dumps({"mime_type": mime_type}), encoding="utf-8")
    resolver = FilesystemMediaResolver({"root": str(tmp_path)})

    with pytest.raises(MediaResolutionError) as caught:
        resolver.resolve(d.MediaRef(media_id=media_id))

    assert caught.value.code is code


def test_capability_manager_builds_filesystem_resolver(monkeypatch, tmp_path):
    from src.capabilities import capability_manager as module

    for name in (
        "SpeechCapability", "SingingCapability", "DynamicCapability",
        "DiaryCapability", "ImageUnderstanding",
    ):
        monkeypatch.setattr(module, name, _Capability)
    manager = module.CapabilityManager(
        {"media_resolution": {"root": str(tmp_path)}}, object())

    assert isinstance(manager.media_resolver, FilesystemMediaResolver)
