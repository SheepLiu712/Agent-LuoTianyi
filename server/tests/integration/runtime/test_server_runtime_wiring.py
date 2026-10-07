"""生产接线：`ServerRuntime._wire_dependencies` 必须把 media_resolver 交给 UserInterface；
`build_websocket_service` 必须把媒体限额推出的入站帧上限交给 WebSocketService。

历史问题一：媒体解析器只在 `get_history` 里逐请求改写共享 helper 状态；若接线漏传，
历史中所有音频的 `audio_available` 会静默变 False。只测 `UserInterface.wire_dependencies`
的 API 无法发现漏传，这里走真正的 `_wire_dependencies`。

历史问题二：入站帧上限若漏传，会静默回落到默认 8 MiB——只有媒体限额被配成非默认值
时才暴露，因此这里用非默认限额断言"配置 → 上限"这条线没断；`WebSocketService()`
的无参默认值已被同一推导口径覆盖，因此还必须在源码级钉住生产装配点本身（见
`test_runtime_initialization_uses_build_websocket_service` 的变异依据）。
"""

from pathlib import Path
from types import SimpleNamespace

import src.server_runtime as server_runtime_module
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
        user_interface=UserInterface(database, media_resolver),
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


def test_media_resolver_reaches_user_interface_at_construction():
    """生产接线必须把 media_resolver 交给 UserInterface（base 已改为构造期注入，cb4c247）。

    漏传会让历史中所有音频的 `audio_available` 静默变 False；这里同时确认
    `_wire_dependencies()` 不会破坏构造期注入的引用。
    """
    resolver = SimpleNamespace(ensure_dependencies=_noop)
    runtime = _runtime(resolver)

    runtime._wire_dependencies()

    assert runtime.user_interface.media_resolver is resolver
    assert runtime.user_interface.user_conversation_helper.media_resolver is resolver


def test_build_websocket_service_uses_configured_media_limit():
    """`build_websocket_service` 必须把 config 里的媒体限额推导结果交给 WebSocketService。

    期望值取自同一个推导函数，但用**非默认**限额，因此函数本身的推导被破坏时必然
    失败。注意：本测试无法发现"生产装配点没有调用本函数"——那条防线由
    `test_runtime_initialization_uses_build_websocket_service` 承担。
    """
    media_limit = 12 * 1024 * 1024
    config = {"infrastructure": {"media_resolution": {"max_encoded_bytes": media_limit}}}

    service = build_websocket_service(config)

    assert isinstance(service, WebSocketService)
    assert service.max_inbound_frame_bytes == resolve_max_inbound_frame_bytes({"max_encoded_bytes": media_limit})
    assert service.max_inbound_frame_bytes != WebSocketService().max_inbound_frame_bytes


def test_runtime_initialization_uses_build_websocket_service():
    """生产装配点必须经 `build_websocket_service(config)` 构造 WebSocketService。

    变异依据（本 PR 复核实测）：把 `initialize` 里的调用点退回 `WebSocketService()`
    后，上面的函数级测试依然全绿——无参默认值在默认媒体限额下与推导结果数值相同，
    两条路不可区分，N1 的"配置 → 上限"会静默断线。完整 `initialize` 离线跑不动
    （需要角色资源与模型配置），因此仿照 `tests/integration/architecture` 的源码级
    断言先例钉住调用点；若装配方式重构，应同步更新本测试。
    """
    source = Path(server_runtime_module.__file__).read_text(encoding="utf-8")

    assert "websocket_service=build_websocket_service(config)," in source
    assert "websocket_service=WebSocketService()" not in source
