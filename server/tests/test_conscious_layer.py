import asyncio
import os
import sys
from dataclasses import dataclass

current_dir = os.getcwd()
if current_dir not in sys.path:
    sys.path.append(current_dir)

from src.agent.attention_planner import AttentionPlanner, TopicAttentionPlan
from src.agent.response_realizer import ResponseRealizer, UserExpressionContext
from src.domain import ActionType, AgentState, MemoryContext, MemoryHit


@dataclass
class FakeTopic:
    topic_id: str = "topic-1"
    topic_content: str = "hello"
    memory_attempts: list[str] = None
    fact_constraints: list[str] = None
    sing_attempts: list[str] = None

    def __post_init__(self):
        self.memory_attempts = self.memory_attempts or ["memory query"]
        self.fact_constraints = self.fact_constraints or ["fact query"]
        self.sing_attempts = self.sing_attempts or ["song request"]


def test_attention_planner_collects_context_and_builds_action_plan():
    planner = AttentionPlanner(target_character_id="luotianyi")

    async def memory_search(queries):
        assert queries == ["memory query"]
        return MemoryContext((MemoryHit(rendered_text="memory hit", score=0.91, query=queries[0]),))

    async def fact_search(constraints):
        assert constraints == ["fact query"]
        return ["fact hit"]

    async def sing_planner(attempts):
        assert attempts == ["song request"]
        return "song-a", "segment-a"

    async def run():
        return await planner.plan_topic_turn(
            user_id="u1",
            topic=FakeTopic(),
            conversation_history="history",
            memory_search=memory_search,
            fact_search=fact_search,
            sing_planner=sing_planner,
            external_context="schedule context",
            agent_state=AgentState(owner_character_id="luotianyi", mood=0.8),
        )

    plan = asyncio.run(run())

    assert isinstance(plan, TopicAttentionPlan)
    assert plan.topic_content == "hello\n\nschedule context"
    assert plan.memory_hits == ["memory hit"]
    assert plan.agent_state is not None
    assert plan.agent_state.mood == 0.8
    assert plan.fact_hits == ["fact hit"]
    assert plan.sing_plan == ("song-a", "segment-a")
    assert plan.attention_notes == ("external_context",)
    assert [action.action_type for action in plan.action_plan.actions] == [
        ActionType.SAY,
        ActionType.SING,
    ]


def test_response_realizer_only_delegates_style_generation_to_main_chat():
    class FakeMainChat:
        def __init__(self):
            self.kwargs = None

        async def generate_response(self, **kwargs):
            self.kwargs = kwargs
            return ["reply"]

    main_chat = FakeMainChat()
    realizer = ResponseRealizer(main_chat)
    plan = TopicAttentionPlan(
        user_id="u1",
        topic_id="topic-1",
        target_character_id="luotianyi",
        topic_content="topic",
        conversation_history="history",
        memory_hits=["memory"],
        fact_hits=["fact"],
        sing_plan=("song", "segment"),
    )

    async def run():
        return await realizer.realize_topic_plan(
            plan=plan,
            user_context=UserExpressionContext(
                nickname="tester",
                description="desc",
                preference_context="prefs",
            ),
        )

    assert asyncio.run(run()) == ["reply"]
    assert main_chat.kwargs == {
        "reply_topic": "topic",
        "user_nickname": "tester",
        "user_description": "desc",
        "preference_context": "prefs",
        "conversation_history": "history",
        "fact_hits": ["fact"],
        "memory_hits": ["memory"],
        "sing_plan": ("song", "segment"),
    }
