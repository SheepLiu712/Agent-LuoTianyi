"""真实事件存储、聊天调度和回复提示词之间的提醒内容传递。"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import src.domain.agent as d
from src.agent import Agent
from src.agent.context import UserContextSnapshot
from src.agent.handlers.stimulus.proactive import FirstLoginHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.infrastructure.persistence.due_events import EventStoreDueEventProvider
from tests.integration.agent.test_topic_reply_pipeline import Conversation, pipeline
from tests.integration.persistence import test_memory_write_skill as memory_write_tests
from tests.integration.stage.test_proactive_due_dispatch import RecordingAgent, connected_manager, wait_until

setup = memory_write_tests.setup

CASES = [
    ("travel", "武康路", "在梧桐树下买了桂花糕，香甜柔软。", "你昨天去了武康路"),
    ("new_song", "洛天依学会了新歌", "权御天下、普通DISCO", "你昨天学了权御天下、普通DISCO"),
    ("holiday", "中秋节", "和家人赏月团圆。", "今天是中秋节"),
    ("birthday", "用户的生日", "这是用户的二十五岁生日。", "今天是用户的生日"),
    ("anniversary", "相识一周年", "去年今天第一次和用户聊天。", "今天是相识一周年"),
]


class ReplyingAgent(RecordingAgent):
    def __init__(self, skills):
        super().__init__()
        handler = FirstLoginHandler(prepared_names=(), prepared_speech=None, skills=skills)
        self.agent = Agent(
            character_id="luotianyi",
            stimulus_router=StimulusRouter(
                [
                    (d.StimulusKind.PROACTIVE_PROMPT_DUE, handler),
                ]
            ),
        )

    async def handle_stimulus(self, request, sink, *, context=None):
        self.stimuli.append(request.stimulus)
        context.conversation = Conversation()
        context.user = SimpleNamespace(read=UserContextSnapshot)
        return await self.agent.handle_stimulus(request, sink, context=context)


async def add_reminder(store, case):
    kind, title, description, _ = case
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    return await store.add_event(
        {
            "character": "luotianyi",
            "event_type": kind,
            "title": title,
            "description": description,
            "source": "system",
            "start_datetime": now - timedelta(days=1) if kind in {"travel", "new_song"} else now,
            "is_personal": kind in {"birthday", "anniversary"},
            "target_user_id": "user" if kind in {"birthday", "anniversary"} else None,
        }
    )


@pytest.mark.parametrize("case", CASES)
async def test_event_details_reach_real_reply_prompt_without_memory_guessing(setup, case):
    store = setup.database.event_store
    event_id = await add_reminder(store, case)
    skills, _, calls = pipeline(attempts=(), queries=())
    agent = ReplyingAgent(skills)
    manager, stage = await connected_manager(EventStoreDueEventProvider(store), agent)
    try:
        assert await stage.dispatch_due_events(merge_all=True)
        await wait_until(lambda: "replier" in calls)
        prompt = calls["replier"]
        assert case[3] in prompt["reply_topic"]
        assert case[2] in prompt["extra_knowledge"]
        assert "有一项到期提醒" not in prompt["reply_topic"]
        assert "recall" not in calls
        assert agent.stimuli[0].events[0].event_id == event_id
    finally:
        await manager.close()


async def test_merged_reminders_keep_each_event_and_exclude_other_users(setup):
    store = setup.database.event_store
    for case in CASES:
        await add_reminder(store, case)
    await store.add_event(
        {
            "character": "luotianyi",
            "event_type": "birthday",
            "title": "别人的私密生日",
            "description": "不得进入提示词",
            "source": "system",
            "start_datetime": datetime.now(ZoneInfo("Asia/Shanghai")),
            "is_personal": True,
            "target_user_id": "other",
        }
    )
    skills, _, calls = pipeline(attempts=(), queries=())
    agent = ReplyingAgent(skills)
    manager, stage = await connected_manager(EventStoreDueEventProvider(store), agent)
    try:
        assert await stage.dispatch_due_events(merge_all=True)
        await wait_until(lambda: "replier" in calls)
        for _, _, description, topic in CASES:
            assert topic in calls["replier"]["reply_topic"]
            assert description in calls["replier"]["extra_knowledge"]
        assert len(agent.stimuli[0].events) == 5
        assert "不得进入提示词" not in calls["replier"]["extra_knowledge"]
    finally:
        await manager.close()


async def test_due_events_use_beijing_calendar_day_at_utc_date_boundary(setup):
    store = setup.database.event_store
    await store.add_event(
        {
            "character": "luotianyi",
            "event_type": "travel",
            "title": "武康路",
            "description": "梧桐落叶",
            "source": "system",
            "start_datetime": datetime(2026, 11, 2, 12),
        }
    )
    from datetime import timezone

    due = EventStoreDueEventProvider(store).list_due(
        character_id="luotianyi",
        user_id="user",
        now=datetime(2026, 11, 2, 16, 30, tzinfo=timezone.utc),
    )
    assert len(due) == 1
    assert due[0].description == "梧桐落叶"
    assert due[0].due_at.utcoffset() == timedelta(hours=8)
