"""入站帧上限的推导口径：覆盖媒体限额，且不得越过传输层上限。

uvicorn 默认 `ws_max_size` 为 16 MiB，而 `server_main` 不设置它（无法跟随热改的
媒体限额）。因此应用层上限必须夹在传输层范围内，否则超限帧会被 1009 断连、
结构化 BAD_MESSAGE 不可达——这正是本 PR 要消除的失败模式在另一个配置区间的复现。
"""

from src.infrastructure.config.frame_limits import (
    DEFAULT_MEDIA_MAX_ENCODED_BYTES,
    INBOUND_FRAME_ENVELOPE_BYTES,
    TRANSPORT_FRAME_LIMIT_BYTES,
    exceeds_transport_limit,
    resolve_max_inbound_frame_bytes,
)
from src.infrastructure.config.secrets import SecretStore
from src.infrastructure.config.validation import RuntimeConfigValidator


def test_default_media_limit_is_below_transport_limit():
    """默认 8 MiB 媒体限额推出的帧上限必须仍在传输层范围内。"""
    limit = resolve_max_inbound_frame_bytes({})

    assert limit == DEFAULT_MEDIA_MAX_ENCODED_BYTES + INBOUND_FRAME_ENVELOPE_BYTES
    assert limit <= TRANSPORT_FRAME_LIMIT_BYTES
    assert exceeds_transport_limit({}) is False


def test_large_media_limit_is_clamped_to_transport_limit():
    """媒体限额远超传输层时必须夹紧，不得宣称一个无法执行的上限。"""
    huge = 64 * 1024 * 1024

    limit = resolve_max_inbound_frame_bytes({"max_encoded_bytes": huge})

    assert limit == TRANSPORT_FRAME_LIMIT_BYTES
    assert limit < huge
    assert exceeds_transport_limit({"max_encoded_bytes": huge}) is True


def test_normal_media_limit_is_not_clamped():
    """未被夹紧的配置仍按媒体限额 + 信封精确推导（不引入新的静默上限）。"""
    media_limit = 12 * 1024 * 1024

    assert resolve_max_inbound_frame_bytes({"max_encoded_bytes": media_limit}) == (
        media_limit + INBOUND_FRAME_ENVELOPE_BYTES
    )
    assert exceeds_transport_limit({"max_encoded_bytes": media_limit}) is False


def _validator(tmp_path, monkeypatch) -> RuntimeConfigValidator:
    monkeypatch.setenv("JWT_SECRET", "jwt")
    monkeypatch.setenv("AMAP_KEY", "amap")
    return RuntimeConfigValidator(
        root_dir=tmp_path,
        secret_store=SecretStore(tmp_path / "secrets.local.env"),
    )


def _frame_limit_items(validation) -> list:
    return [item for item in validation["items"] if item["name"] == "media_resolution.max_encoded_bytes"]


def test_validator_warns_when_media_limit_exceeds_transport_limit(tmp_path, monkeypatch):
    """配置与部署不匹配（媒体限额大于传输层）必须在控制台可见，且不阻断启动。"""
    validator = _validator(tmp_path, monkeypatch)
    config = {"infrastructure": {"media_resolution": {"max_encoded_bytes": 64 * 1024 * 1024}}}

    matched = _frame_limit_items(validator.validate(config))

    assert len(matched) == 1
    assert matched[0]["status"] == "warning"
    assert matched[0]["severity"] == "warning"


def test_validator_is_silent_for_default_media_limit(tmp_path, monkeypatch):
    """默认/常规媒体限额不产生该类告警。"""
    validator = _validator(tmp_path, monkeypatch)
    config = {"infrastructure": {"media_resolution": {"max_encoded_bytes": DEFAULT_MEDIA_MAX_ENCODED_BYTES}}}

    assert _frame_limit_items(validator.validate(config)) == []
