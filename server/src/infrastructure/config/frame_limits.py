"""入站 WebSocket 帧上限的统一口径（应用层与传输层必须协同）。

图片以 base64 整帧上行，应用层入站帧上限必须覆盖媒体库允许的最大编码字节，
否则真实手机照片会在应用层被拒收（历史上限 128 KiB）。

同时，只有传输层放行的帧才能进入应用层检查：`server_main.py` 不设置
`uvicorn` 的 `ws_max_size`（该值只能在 `Config` 构造时确定，无法跟随管理端热改的
媒体限额），因此以 uvicorn 默认值 `16 MiB` 作为传输层上限。若应用层上限超过它，
超限帧会先在传输层被 `1009` 断连，`WebSocketService` 的结构化 BAD_MESSAGE
永远不可达——正是本模块要避免的失败模式。

媒体限额确实需要更大图片时，必须在 `server_main` 显式提高 `ws_max_size`，
并同步本模块的 `TRANSPORT_FRAME_LIMIT_BYTES`。
"""

from __future__ import annotations

from typing import Any

# uvicorn.Config 默认 ws_max_size（16 MiB）；提高它必须同步修改本常量。
TRANSPORT_FRAME_LIMIT_BYTES = 16 * 1024 * 1024

# 媒体库默认允许的最大 base64 编码字节（与 PermanentMediaStore 缺省值同口径）。
DEFAULT_MEDIA_MAX_ENCODED_BYTES = 8 * 1024 * 1024

# JSON 信封余量：整帧 = base64 载荷 + 事件类型 / client_msg_id / mime_type 等字段。
INBOUND_FRAME_ENVELOPE_BYTES = 256 * 1024


def resolve_media_max_encoded_bytes(media_config: dict[str, Any] | None = None) -> int:
    """媒体库允许的最大 base64 编码字节，非法或缺省时回落默认值。"""
    if isinstance(media_config, dict):
        configured = media_config.get("max_encoded_bytes")
        if type(configured) is int and configured > 0:
            return configured
    return DEFAULT_MEDIA_MAX_ENCODED_BYTES


def resolve_max_inbound_frame_bytes(media_config: dict[str, Any] | None = None) -> int:
    """入站帧上限 = 媒体编码上限 + 信封余量，且不超过传输层可放行范围。

    夹紧只保证"应用层不会宣称一个它无法执行的上限"；真正超过传输层上限的帧
    仍会在传输层被断开，需要提高 `ws_max_size`（配置校验会给出 warning）。
    """
    desired = resolve_media_max_encoded_bytes(media_config) + INBOUND_FRAME_ENVELOPE_BYTES
    return min(desired, TRANSPORT_FRAME_LIMIT_BYTES)


def exceeds_transport_limit(media_config: dict[str, Any] | None = None) -> bool:
    """媒体限额推出的帧上限是否超出传输层可放行范围。"""
    desired = resolve_media_max_encoded_bytes(media_config) + INBOUND_FRAME_ENVELOPE_BYTES
    return desired > TRANSPORT_FRAME_LIMIT_BYTES
