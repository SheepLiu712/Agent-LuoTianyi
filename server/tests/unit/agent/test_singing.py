"""真实 SING 路由与演唱技能的离线测试。"""

import threading
from dataclasses import replace

import pytest

import src.domain.agent as d
from src.agent import Agent
from src.agent.handlers.action.router import ActionRouter
from src.agent.handlers.action.sing import SingHandler
from src.agent.skills.expression.singing import EmptySongAudioError, SingingSkill
from support.routing_support import Sink, plan_and_context
from support.skill_support import invocation


class Singing:
    """记录调用并返回固定音频或抛出指定错误的演唱替身。"""

    def __init__(self, audio=b"\x00\x01wav", error=None):
        self.audio = audio
        self.error = error
        self.calls = []

    def sing(self, character_id, song_name=None, segment=None):
        self.calls.append((character_id, song_name, segment, threading.get_ident()))
        if self.error:
            raise self.error
        return self.audio


def sing_plan(expression=True):
    plan, context = plan_and_context()
    sing = d.Sing(action_id="a1", song_id="歌曲", segment_id="副歌",
                  expression=d.ChangeExpression(expression_id="唱歌") if expression else None)
    return replace(plan, actions=(sing,)), context


def agent(singing):
    return Agent(character_id="luotianyi", action_router=ActionRouter([
        (d.ActionKind.SING, SingHandler("luotianyi", SingingSkill({}, backend=singing)))]))


@pytest.mark.asyncio
async def test_sing_route_outputs_expression_audio_and_end():
    singing = Singing()
    plan, context = sing_plan()
    sink = Sink()
    report = await agent(singing).realize_action_plan(plan, context, sink)
    assert report.status is d.ExecutionStatus.COMPLETED
    assert [o.kind for o in sink.values] == [
        d.AgentOutputKind.EXPRESSION, d.AgentOutputKind.AUDIO_CHUNK, d.AgentOutputKind.MESSAGE_END]
    assert sink.values[0].expression.expression_id == "唱歌"
    assert sink.values[1].data == b"\x00\x01wav"
    assert sink.values[1].framing is d.AudioFraming.COMPLETE_FILE
    assert sink.values[1].delivery is d.OutputDelivery.CONVERSATION
    assert sink.values[-1].status is d.MessageEndStatus.COMPLETED
    assert [o.sequence_no for o in sink.values] == [0, 1, 2]
    assert all(o.action_id == "a1" for o in sink.values)
    assert singing.calls[0][:3] == ("luotianyi", "歌曲", "副歌")
    assert singing.calls[0][3] != threading.get_ident()


@pytest.mark.asyncio
async def test_unavailable_segment_fails_with_empty_audio_terminal():
    singing = Singing(audio=None)
    plan, context = sing_plan(expression=False)
    sink = Sink()
    report = await agent(singing).realize_action_plan(plan, context, sink)
    assert report.status is d.ExecutionStatus.FAILED
    assert report.error_code is d.ExecutionErrorCode.AUDIO_EMPTY
    assert [o.kind for o in sink.values] == [d.AgentOutputKind.MESSAGE_END]
    assert sink.values[-1].status is d.MessageEndStatus.FAILED
    assert sink.values[-1].error_code is d.AudioErrorCode.EMPTY_AUDIO


@pytest.mark.asyncio
async def test_sing_generation_error_stops_plan():
    singing = Singing(error=RuntimeError("boom"))
    plan, context = sing_plan(expression=False)
    sink = Sink()
    report = await agent(singing).realize_action_plan(plan, context, sink)
    assert report.error_code is d.ExecutionErrorCode.AUDIO_GENERATION_FAILED
    assert sink.values[-1].status is d.MessageEndStatus.FAILED
    assert sink.values[-1].error_code is d.AudioErrorCode.GENERATION_FAILED


@pytest.mark.asyncio
async def test_singing_skill_rejects_blank_identity():
    skill = SingingSkill({}, backend=Singing())
    with pytest.raises(ValueError):
        await skill.render(invocation(character_id=""), song_id="歌曲", segment_id="副歌")


@pytest.mark.asyncio
async def test_singing_skill_raises_when_unavailable():
    skill = SingingSkill({}, backend=Singing(audio=None))
    with pytest.raises(EmptySongAudioError):
        await skill.render(invocation(), song_id="歌曲", segment_id="副歌")
