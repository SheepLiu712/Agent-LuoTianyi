"""逐字模型输出经真实回复处理器、行动计划和 SayHandler 提前进入 TTS。"""

import asyncio
from contextlib import aclosing
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from support.call_apology import _Plans, _request, _stimulus
from support.reply_skill import make_reply_skill
from support.retrieval import stub_retrieval, stub_singing
from support.routing_support import Sink, request

import src.domain.agent as d
from src.agent import Agent
from src.agent.context import UserContextSnapshot
from src.agent.handlers.action.router import ActionRouter
from src.agent.handlers.action.say import SayHandler
from src.agent.handlers.reply_skills import ReplySkills
from src.agent.handlers.stimulus.chat import ChatReplyHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.skills.cognitive._prompt_assembly import RealizationPromptAssembler
from src.agent.skills.cognitive._reply_resources import ReplyResources
from src.agent.skills.cognitive._response_parser import StructuredResponseParser
from src.agent.skills.contracts import ReplyDraft, TopicExtraction
from src.agent.skills.expression.prepared_speech import PreparedSpeechCatalog
from src.agent.skills.expression.speaking.skill import SpeakingAudioChunk
from src.domain import MemoryContext
from src.domain.call import CallAudioSemantic
from src.infrastructure.models.llm.module import LLMModule


def parser():
    mapping = {"中性": ("微笑脸", "normal"), "开心": ("开心脸", "happy"), "难过": ("难过脸", "sad")}
    return StructuredResponseParser(
        default_draft=ReplyDraft("", "", "normal", "微笑脸"), tone_mapper=lambda tone: mapping[tone]
    )


class CharacterStream:
    default_parameters = {}

    def __init__(self, text, *, gate_after=None, fail=False):
        self.text, self.gate_after, self.fail = text, gate_after, fail
        self.release = asyncio.Event()
        self.closed = False
        self.finished = False
        self.calls = 0

    def get_interface_info(self):
        return {"model": "逐字模拟模型", "type": "test"}

    async def stream_response(self, prompt, **kwargs):
        self.calls += 1
        try:
            for index, char in enumerate(self.text, 1):
                yield {"content": char}
                if index == self.gate_after:
                    await self.release.wait()
                    if self.fail:
                        raise RuntimeError("模拟生成中断")
            self.finished = True
            yield {"usage": {"total_tokens": len(self.text)}}
        finally:
            self.closed = True


def module(provider):
    return LLMModule("reply", {}, SimpleNamespace(render=lambda **kwargs: "角色和记忆上下文"), provider, stream=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("chunk_size", [1, 2, 1000])
async def test_sentence_threshold_tags_and_spoken_content(chunk_size):
    text = "[开心]一二三四五六七，一。八九十甲乙丙丁戊！[难过]（轻轻叹气，稍作停顿）子丑寅卯辰巳午未？尾声"
    provider = CharacterStream(text)

    async def chunks(prompt, **kwargs):
        for index in range(0, len(text), chunk_size):
            yield {"content": text[index : index + chunk_size]}

    provider.stream_response = chunks
    skill = make_reply_skill({"luotianyi": generator(provider)})
    result = [
        draft async for draft in skill.generate("luotianyi", reply_topic="测试回复", user_context=UserContextSnapshot())
    ]
    assert [draft.sound_content for draft in result] == [
        "一二三四五六七，一。",
        "八九十甲乙丙丁戊！",
        "子丑寅卯辰巳午未？",
        "尾声",
    ]
    assert [(draft.tone, draft.expression) for draft in result] == [
        ("happy", "开心脸"),
        ("happy", "开心脸"),
        ("sad", "难过脸"),
        ("sad", "难过脸"),
    ]


class Memory:
    async def search_memory_context_for_topic(self, *args):
        return MemoryContext()


class Topics:
    async def extract(self, *args, **kwargs):
        return TopicExtraction()


def generator(provider):
    result = ReplyResources.__new__(ReplyResources)
    result.llm = module(provider)
    result.character_name = "天依"
    result.character_persona = "喜欢音乐"
    result.speaking_style = "自然"
    result.prompt_assembler = RealizationPromptAssembler()
    result.response_parser = parser()
    return result


class Speaking:
    def __init__(self):
        self.spoken = []
        self.first = asyncio.Event()

    async def speak(self, invocation, *, text, tone, output_format=None):
        self.spoken.append((text, tone.value))
        self.first.set()
        framing = d.AudioFraming.RAW_PCM if output_format else d.AudioFraming.FILE_FRAGMENT
        yield SpeakingAudioChunk(b"\0\0", framing, output_format)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True], ids=["complete", "failure_after_first_sentence"])
async def test_long_character_stream_delivers_tts_before_generation_finishes(fail):
    call = False
    first = "今天我们一起去公园散步，"
    rest = "然后坐在湖边欣赏风景。" * 12
    provider = CharacterStream("[开心]" + first + rest, gate_after=len("[开心]" + first), fail=fail)
    generators = {"luotianyi": generator(provider)}
    catalog = PreparedSpeechCatalog({})
    value = replace(request(), prepared_inputs=(d.PreprocessedInput(stimulus_id="m2", text="今天做什么"),))
    handler = ChatReplyHandler(
        ReplySkills(
            retrieval=stub_retrieval({"luotianyi": Memory()}),
            singing=stub_singing(SimpleNamespace()),
            reply=make_reply_skill(generators),
            topic_extraction=Topics(),
        )
    )
    context = _Plans().context
    context.identity = SimpleNamespace(
        character_id="luotianyi", user_id=value.interaction.user_id, interaction_id=value.interaction.interaction_id
    )
    speaking, output, delivered = Speaking(), Sink(), []
    agent = Agent(
        character_id="luotianyi",
        stimulus_router=StimulusRouter(((value.stimulus.kind, handler),)),
        action_router=ActionRouter(((d.ActionKind.SAY, SayHandler("luotianyi", speaking, catalog)),)),
    )

    async def realize(plan):
        delivered.append(plan)
        if all(isinstance(action, d.Say) for action in plan.actions):
            execution = await agent.realize_action_plan(
                plan,
                d.ExecutionContext(
                    execution_id=f"execution-{plan.plan_ordinal}",
                    interaction_id=value.interaction.interaction_id,
                    current_interaction_revision=value.interaction.interaction_revision,
                    cancellation=d.CancellationToken(),
                    interaction_context=context,
                    call_output_permit=SimpleNamespace(allows=lambda _: True) if call else None,
                ),
                output,
            )
            assert execution.status is d.ExecutionStatus.COMPLETED
        return d.PlanReceipt(plan_id=plan.plan_id, status=d.PlanAcceptanceStatus.ACCEPTED)

    task = asyncio.create_task(agent.handle_stimulus(value, Sink(realize), context=context))
    try:
        await asyncio.wait_for(speaking.first.wait(), 2)
        assert not task.done()
        assert not provider.finished
        assert speaking.spoken == [(first, "happy")]
        provider.release.set()
        report = await asyncio.wait_for(task, 2)
    finally:
        provider.release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert provider.calls == 1
    assert provider.closed
    expected = first if fail else first + rest
    assert "".join(text for text, _ in speaking.spoken) == expected
    assert report.request_status is (d.HandlingRequestStatus.FAILED if fail else d.HandlingRequestStatus.COMPLETED)
    action_ids = [action.action_id for plan in delivered for action in plan.actions]
    assert len(action_ids) == len(set(action_ids))
    if call:
        assert context.conversation.entries == []
    else:
        assert "".join(entry.content.text for entry in context.conversation.entries) == expected


@pytest.mark.asyncio
async def test_singing_keeps_complete_draft_and_is_not_split_at_punctuation():
    provider = CharacterStream("[开心]一二三四五六七八，九十。\n[sing] 《歌，曲。名》")
    skill = make_reply_skill({"luotianyi": generator(provider)})
    result = [
        draft
        async for draft in skill.generate(
            "luotianyi", reply_topic="唱歌", user_context=UserContextSnapshot(), sing_plan=("歌，曲。名", "副歌")
        )
    ]
    assert result[0].sound_content == "一二三四五六七八，九十。"
    assert result[1].sing == ("歌，曲。名", "副歌")


@pytest.mark.asyncio
@pytest.mark.parametrize("same_character", [False, True], ids=["different_characters", "same_character"])
async def test_shared_reply_routes_persona_and_isolates_concurrent_drafts(same_character):
    calls = []
    entered = asyncio.Event()
    release = asyncio.Event()

    class Model:
        stream = True

        async def generate_response(self, *, on_delta, **prompt):
            calls.append(prompt)
            if len(calls) == 2:
                entered.set()
            await on_delta("[开心]" + prompt["reply_topic"][:4])
            await release.wait()
            await on_delta(prompt["reply_topic"][4:])

    first = generator(CharacterStream(""))
    second = generator(CharacterStream(""))
    first.character_name, second.character_name = "角色甲", "角色乙"
    first.llm = second.llm = Model()
    skill = make_reply_skill({"a": first, "b": second})

    async def collect(character_id, text):
        async with aclosing(
            skill.generate(character_id, reply_topic=text, user_context=UserContextSnapshot())
        ) as stream:
            return [draft async for draft in stream]

    tasks = [
        asyncio.create_task(collect("a", "今天我们一起去公园散步。")),
        asyncio.create_task(collect("a" if same_character else "b", "明天我们一起去海边听歌。")),
    ]
    try:
        await asyncio.wait_for(entered.wait(), 2)
        release.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks), 2)
    finally:
        release.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    assert ["".join(draft.content for draft in result) for result in results] == [
        "今天我们一起去公园散步。",
        "明天我们一起去海边听歌。",
    ]
    assert [call["character_name"] for call in calls] == ["角色甲", "角色甲" if same_character else "角色乙"]


@pytest.mark.asyncio
async def test_closing_reply_stream_stops_provider_before_remaining_reply():
    first = "[开心]今天我们一起去公园散步，"
    provider = CharacterStream(first + "然后去听音乐。", gate_after=len(first))
    skill = make_reply_skill({"luotianyi": generator(provider)})
    async with aclosing(
        skill.generate("luotianyi", reply_topic="今天做什么", user_context=UserContextSnapshot())
    ) as stream:
        draft = await asyncio.wait_for(anext(stream), 2)
        assert draft.content == first.removeprefix("[开心]")
    assert provider.closed
    assert not provider.finished


@pytest.mark.asyncio
async def test_provider_cancellation_ends_reply_stream_without_hanging():
    class CancelledModel:
        stream = True

        async def generate_response(self, **kwargs):
            raise asyncio.CancelledError()

    resource = generator(CharacterStream(""))
    resource.llm = CancelledModel()
    skill = make_reply_skill({"luotianyi": resource})
    async with aclosing(
        skill.generate("luotianyi", reply_topic="测试取消", user_context=UserContextSnapshot())
    ) as stream:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(anext(stream), 2)


@pytest.mark.asyncio
async def test_complete_and_streaming_models_use_same_draft_rules():
    text = "[开心]今天我们一起去公园散步，然后去听音乐。[难过]（叹气）今天下雨了。"
    streaming = generator(CharacterStream(text))
    complete = generator(CharacterStream(""))

    async def response(**kwargs):
        return text

    complete.llm = SimpleNamespace(stream=False, generate_response=response)
    skill = make_reply_skill({"streaming": streaming, "complete": complete})
    results = []
    for character_id in ("streaming", "complete"):
        results.append(
            [
                draft
                async for draft in skill.generate(
                    character_id, reply_topic="今天做什么", user_context=UserContextSnapshot()
                )
            ]
        )
    assert results[0] == results[1]
    assert len(results[0]) == 3


@pytest.mark.parametrize("scene", ["chat", "call"])
async def test_reply_scene_reaches_rendered_model_prompt(scene):
    import json
    from pathlib import Path

    from src.infrastructure.models.llm.prompts import PromptTemplate

    prompts = []
    provider = CharacterStream("[中性]嗯，我在呢。")
    original = provider.stream_response

    async def capture(prompt, **kwargs):
        prompts.append(prompt)
        async for chunk in original(prompt, **kwargs):
            yield chunk

    provider.stream_response = capture
    resource = generator(provider)
    path = Path(__file__).resolve().parents[3] / "res/agent/prompts/topic_reply_prompt.json"
    template = PromptTemplate("\n".join(json.loads(path.read_text(encoding="utf-8"))["template"]))
    resource.llm = LLMModule("reply", {}, template, provider, stream=True)
    skill = make_reply_skill({"luotianyi": resource})
    drafts = [
        draft
        async for draft in skill.generate(
            "luotianyi", scene=scene, reply_topic="你好", user_context=UserContextSnapshot()
        )
    ]
    assert drafts[0].sound_content == "嗯，我在呢。"
    assert len(prompts) == 1
    assert ("实时电话通话" in prompts[0]) == (scene == "call")
    assert ("聊天消息场景" in prompts[0]) == (scene == "chat")
    if scene == "call":
        assert "一到两句短句" in prompts[0]
        assert "语气词" in prompts[0]
