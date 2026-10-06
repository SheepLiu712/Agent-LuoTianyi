"""生产接线：`ServerRuntime._wire_dependencies` 必须把 media_resolver 交给 UserInterface。

历史问题：媒体解析器只在 `get_history` 里逐请求改写共享 helper 状态；若接线漏传，
历史中所有音频的 `audio_available` 会静默变 False。只测 `UserInterface.wire_dependencies`
的 API 无法发现漏传，这里走真正的 `_wire_dependencies`。
"""

from types import SimpleNamespace

from src.server_runtime import ServerRuntime
from src.web.http.user_interface import UserInterface


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
