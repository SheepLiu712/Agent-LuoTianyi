"""测试中的真实 Manager / Adapter 装配，与组合根使用相同的窄依赖。"""

from src.stage import StageManager


def make_stage_manager(*, adapter, **kwargs):
    manager = StageManager(
        chat_output_sink=adapter.output_sink,
        detach_stage_binding=adapter.detach_stage_binding,
        **kwargs,
    )
    adapter.initialize(manager)
    manager._test_chat_adapter = adapter
    return manager
