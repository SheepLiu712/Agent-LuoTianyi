"""测试中的真实 Manager / Adapter 装配，与组合根使用相同的窄依赖。"""

from src.stage import StageManager


def make_stage_manager(*, adapter, **kwargs):
    async def call_output_sink(call_id, output):
        await manager._test_call_adapter.submit_output(call_id, output)

    kwargs.setdefault("call_output_sink", call_output_sink)
    if kwargs.get("call_sessions") is not None:
        from support.realtime_speech import FakeRealtimeSpeechSessionFactory

        # 生命周期与协议测试不验证存储方法；结算测试须显式提供真实存储或替换 consumer。
        kwargs.setdefault("conversation_service", object())
        kwargs.setdefault("call_maintenance_batches", object())
        kwargs.setdefault("realtime_speech_factory", FakeRealtimeSpeechSessionFactory())
    manager = StageManager(
        chat_output_sink=adapter.output_sink,
        detach_stage_binding=adapter.detach_stage_binding,
        **kwargs,
    )
    manager._test_call_resources = {
        key: kwargs.get(source)
        for key, source in {
            "get_agent": "get_agent",
            "get_context_factory": "get_context_factory",
            "call_sessions": "call_sessions",
            "conversation_service": "conversation_service",
            "call_maintenance_batches": "call_maintenance_batches",
            "call_metrics": "call_metrics",
            "speech_factory": "realtime_speech_factory",
            "output_sink": "call_output_sink",
            "wall_clock": "wall_clock",
        }.items()
    }
    if "monotonic" in kwargs:
        manager._test_call_resources["monotonic"] = kwargs["monotonic"]
    adapter.initialize(manager)
    manager._test_chat_adapter = adapter
    return manager


def make_call_adapter(*, manager, **kwargs):
    """将测试协议门面接到组合根提前注入的稳定输出路由。"""
    from src.adapter.websocket.call_v1 import CallWebSocketAdapter

    adapter = CallWebSocketAdapter(manager=manager, **kwargs)
    manager._test_call_adapter = adapter
    return adapter


async def create_call_stage(manager, claim, *, transport, speech_factory, call_metrics=None, **kwargs):
    """底层交接测试装配真实通话服务；生产接入不接受逐次资源注入。"""
    from support.call_output import output_sink

    from src.stage.call_stage import bind_call_stage_creator

    resources = dict(manager._test_call_resources)
    resources.update(output_sink=output_sink(transport), speech_factory=speech_factory, call_metrics=call_metrics)
    manager._call_stage_creator = bind_call_stage_creator(**resources)
    return await manager._create_call_stage(claim, **kwargs)


async def start_call_stage(**kwargs):
    """仅测试底层实时生命周期；生产创建还须装配持久化结算。"""
    from src.stage.call_stage import CallStage

    stage = CallStage(**kwargs)
    await stage.start()
    return stage
