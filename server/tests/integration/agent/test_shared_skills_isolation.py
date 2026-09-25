"""所有 Agent 共用 Skill 实例，同时按调用身份隔离角色和用户。"""

import asyncio

import pytest

import src.domain.agent as d
from src.agent.skills.cognitive import ReplyDraft, ResponseCompositionSkill
from src.agent.skills.contracts import SkillInvocation
from src.agent_runtime.agent_runtime import AgentRuntime


class Memory:
    def __init__(self, label: str) -> None:
        self.label = label
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    async def search_memory_context_for_topic(self, user_id: str, queries: list[str]):
        self.calls.append((user_id, tuple(queries)))
        label = self.label

        class Recall:
            hits = ()

            def render_for_prompt(self):
                return [f"{label}:memory"]

        return Recall()


class Generator:
    def __init__(self, label: str, gate: asyncio.Event) -> None:
        self.label = label
        self.gate = gate
        self.calls: list[dict] = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        await self.gate.wait()
        return (
            ReplyDraft(
                content=f"{self.label}:{kwargs['reply_topic']}",
                sound_content="",
                tone="normal",
                expression=None,
            ),
        )


class Singing:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def build_sing_plan(self, character_id, attempts, **kwargs):
        self.calls.append(character_id)
        return None

    def get_segment_lyrics(self, character_id, song, segment):
        return ""


def invocation(character_id: str, user_id: str) -> SkillInvocation:
    return SkillInvocation(
        character_id=character_id,
        user_id=user_id,
        interaction_id=f"interaction-{user_id}",
        cancellation=d.CancellationToken(),
    )


@pytest.mark.asyncio
async def test_shared_composition_keeps_two_agents_and_users_isolated():
    gate = asyncio.Event()
    memories = {"agent-a": Memory("a"), "agent-b": Memory("b")}
    generators = {
        "agent-a": Generator("a", gate),
        "agent-b": Generator("b", gate),
    }
    singing = Singing()
    skill = ResponseCompositionSkill(
        {},
        memories=memories,
        singing=singing,
        generators=generators,
    )

    tasks = (
        asyncio.create_task(
            skill.compose(
                invocation("agent-a", "user-a"),
                user_context=type("User", (), {})(),
                reply_topic="topic-a",
                conversation_history="",
                memory_queries=("query-a",),
                sing_attempts=("song-a",),
            )
        ),
        asyncio.create_task(
            skill.compose(
                invocation("agent-b", "user-b"),
                user_context=type("User", (), {})(),
                reply_topic="topic-b",
                conversation_history="",
                memory_queries=("query-b",),
                sing_attempts=("song-b",),
            )
        ),
    )
    await asyncio.sleep(0)
    gate.set()
    replies_a, replies_b = await asyncio.gather(*tasks)

    assert memories["agent-a"].calls == [("user-a", ("query-a",))]
    assert memories["agent-b"].calls == [("user-b", ("query-b",))]
    assert sorted(singing.calls) == ["agent-a", "agent-b"]
    assert replies_a[0].content == "a:topic-a"
    assert replies_b[0].content == "b:topic-b"


def test_runtime_agents_reference_the_same_skill_instances(runtime_dependencies):
    kwargs, _ = runtime_dependencies
    runtime = AgentRuntime(**kwargs)
    try:
        first = runtime.get_agent("luotianyi")
        second = runtime.get_agent("miku")
        first_say = first._action_router.resolve(d.ActionKind.SAY)
        second_say = second._action_router.resolve(d.ActionKind.SAY)
        first_reply = first._stimulus_router.resolve(d.StimulusKind.INTERACTION_DEADLINE)
        second_reply = second._stimulus_router.resolve(d.StimulusKind.INTERACTION_DEADLINE)

        assert first_say._speaking is runtime.skills.speaking
        assert second_say._speaking is runtime.skills.speaking
        assert first_reply._composition is runtime.skills.response_composition
        assert second_reply._composition is runtime.skills.response_composition
    finally:
        asyncio.run(runtime.shutdown())
