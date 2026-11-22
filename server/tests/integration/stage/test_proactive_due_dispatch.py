"""普通登录不再独立触发事件提醒，冷场发言必须经过角色热度计时器。"""

import asyncio
import pytest
from support.stage_manager import make_stage_manager
from src.adapter.websocket.chat import WebSocketAdapter
from support.stage_support import RecordingAgent, StageContextFactory


@pytest.mark.asyncio
async def test_regular_login_no_longer_schedules_reminders():
    agent = RecordingAgent()
    manager = make_stage_manager(
        adapter=WebSocketAdapter(), get_agent=lambda _: agent, get_context_factory=lambda _: StageContextFactory()
    )
    try:
        assert manager.record_login("user", "luotianyi", elapsed_from_last_login=86400) is False
        await asyncio.sleep(0.02)
        assert agent.requests.empty()
    finally:
        await manager.close()
