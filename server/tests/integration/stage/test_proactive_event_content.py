"""真实事件存储进入角色主动话题，不再通过 Stage 到期提醒入口。"""

from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from support.routing_support import Sink, request
import src.domain.agent as d
from src.agent import Agent
from src.agent.handlers.stimulus.proactive_speech import ProactiveSpeechHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.infrastructure.persistence.due_events import EventStoreDueEventProvider
from tests.integration.agent.test_topic_reply_pipeline import context, pipeline
from tests.integration.persistence import test_memory_write_skill as memory_write_tests

setup = memory_write_tests.setup

CASES = [
    ("travel", "武康路", "在梧桐树下买了桂花糕，香甜柔软。", "你昨天去了武康路"),
    ("new_song", "洛天依学会了新歌", "权御天下、普通DISCO", "你昨天学了权御天下、普通DISCO"),
    ("holiday", "中秋节", "和家人赏月团圆。", "今天是中秋节"),
    ("birthday", "用户的生日", "这是用户的二十五岁生日。", "今天是用户的生日"),
    ("anniversary", "相识一周年", "去年今天第一次和用户聊天。", "今天是相识一周年"),
]


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
            "target_user_id": "u" if kind in {"birthday", "anniversary"} else None,
        }
    )


async def generate(store):
    skills, _, calls = pipeline(attempts=(), queries=())
    handler = ProactiveSpeechHandler(skills=skills, events=EventStoreDueEventProvider(store))
    agent = Agent(
        character_id="luotianyi", stimulus_router=StimulusRouter([(d.StimulusKind.PROACTIVE_SPEECH_DUE, handler)])
    )
    req = request()
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    req = replace(
        req,
        stimulus=d.ProactiveSpeechDue(
            stimulus_id="due",
            schema_version=1,
            occurred_at=now,
            source=d.StimulusSource.AGENT,
            target_character_ids=("luotianyi",),
            user_id="u",
            ephemeral=True,
            generation=1,
        ),
        interaction=replace(req.interaction, pending_stimuli=(), now=now),
    )
    sink = Sink()
    report = await agent.handle_stimulus(req, sink, context=context())
    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    return calls["replier"], sink.values


@pytest.mark.parametrize("case", CASES)
async def test_event_details_reach_real_reply_prompt_without_memory_guessing(setup, case):
    store = setup.database.event_store
    event_id = await add_reminder(store, case)
    prompt, plans = await generate(store)
    assert case[3] in prompt["reply_topic"]
    assert case[2] in prompt["extra_knowledge"]
    assert plans[0].actions[-1].event_id == event_id


async def test_other_users_event_is_not_used_as_topic(setup):
    store = setup.database.event_store
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
    prompt, plans = await generate(store)
    assert "上下文" in prompt["reply_topic"]
    assert "不得进入提示词" not in str(prompt)
    assert not any(isinstance(a, d.MarkTopicShared) for p in plans for a in p.actions)


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
