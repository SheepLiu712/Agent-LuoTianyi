"""生产接线：`ServerRuntime._wire_dependencies` 必须把 media_resolver 交给 UserInterface；
`build_websocket_service` 必须把媒体限额推出的入站帧上限交给 WebSocketService。

历史问题一：媒体解析器只在 `get_history` 里逐请求改写共享 helper 状态；若接线漏传，
历史中所有音频的 `audio_available` 会静默变 False。只测 `UserInterface.wire_dependencies`
的 API 无法发现漏传，这里走真正的 `_wire_dependencies`。

历史问题二：入站帧上限若漏传，会静默回落到默认 8 MiB——只有媒体限额被配成非默认值
时才暴露，因此这里用非默认限额断言"配置 → 上限"这条线没断。
"""

from types import SimpleNamespace

from src.infrastructure.config.frame_limits import resolve_max_inbound_frame_bytes
from src.server_runtime import ServerRuntime, build_websocket_service
from src.web.http.user_interface import UserInterface
from src.web.websocket.service import WebSocketService


def _noop(*args, **kwargs) -> None:
    return None


def _runtime(media_resolver) -> ServerRuntime:
    database = SimpleNamespace(
        wire_dependencies=_noop,
        ensure_dependencies=_noop,
    )
    return ServerRuntime(
        user_interface=UserInterface(database),
        websocket_service=SimpleNamespace(),
        world=SimpleNamespace(wire_dependencies=_noop, ensure_dependencies=_noop),
        database_manager=database,
        agent_runtime=SimpleNamespace(wire_dependencies=_noop, ensure_dependencies=_noop),
        media_resolver=media_resolver,
        llm_service=SimpleNamespace(ensure_dependencies=_noop),
        observability=SimpleNamespace(),
        client_llm_executor=SimpleNamespace(),
        owns_observability=False,
    )


def test_wire_dependencies_injects_media_resolver_into_user_interface():
    resolver = SimpleNamespace(ensure_dependencies=_noop)
    runtime = _runtime(resolver)

    runtime._wire_dependencies()

    assert runtime.user_interface.media_resolver is resolver
    assert runtime.user_interface.user_conversation_helper.media_resolver is resolver


def test_build_websocket_service_uses_configured_media_limit():
    """生产接线必须把 config 里的媒体限额推导结果交给 WebSocketService。

    期望值取自同一个推导函数，但用**非默认**限额，因此漏传 kwarg（静默回落 8 MiB）
    必然导致断言失败——只断言"服务已构造"是无法发现该漏传的。
    """
    media_limit = 12 * 1024 * 1024
    config = {"infrastructure": {"media_resolution": {"max_encoded_bytes": media_limit}}}

    service = build_websocket_service(config)

    assert isinstance(service, WebSocketService)
    assert service.max_inbound_frame_bytes == resolve_max_inbound_frame_bytes({"max_encoded_bytes": media_limit})
    assert service.max_inbound_frame_bytes != WebSocketService().max_inbound_frame_bytes
