"""聊天 pipeline 的准备、聚合、取消、执行及维护流程。"""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from test_chat_stage import RecordingAgent, cleanup, plan, report, setup, stimulus, take

import src.domain.agent as d
from src.agent import Agent
from src.agent.handlers.stimulus.chat import (
    ChatPreprocessingHandler,
    ChatReflectionHandler,
)
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.processing.plan_emitter import ActionPlanDraft
from src.agent.skills.cognitive import ImagePreprocessingSkill
from src.capabilities.media_resolution import ResolvedMedia


async def until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0)
    await asyncio.wait_for(wait(), 2)


def ids(req):
    return tuple(s.stimulus_id for s in req.interaction.pending_stimuli)


class _Understanding:
    def extract_terms(self, text):
        return ()


def touch():
    return stimulus(d.TouchInteraction, body_regions=(d.BodyRegion(value="head"),), click_frequency=None)


@pytest.mark.asyncio
async def test_slow_image_fast_text_preserve_order_and_wait_after_last_completion():
    gate = asyncio.Event()
    replies = asyncio.Queue()
    image = stimulus(d.ImageMessage, media_ref=d.MediaRef(media_id="image"), caption=None, client_msg_id="image")
    text = stimulus()
    async def handle(req, sink):
        if req.purpose is d.HandlePurpose.REFLECT:
            return report(req)
        if req.stimulus is image:
            await gate.wait()
        if isinstance(req.stimulus, d.InteractionDeadline):
            replies.put_nowait(req)
            return report(req, consumed=ids(req))
        return report(req)
    stage, _, adapter, _, _ = await setup(RecordingAgent(handle), {"response_wait": 0.04})
    try:
        stage.stimulus_input_sink.submit(image)
        stage.stimulus_input_sink.submit(text)
        await until(lambda: stage._pending[text.stimulus_id].prepared is not None)
        await asyncio.sleep(0.06)
        assert replies.empty() and stage._deadline is None
        finished = datetime.now(timezone.utc)
        gate.set()
        req = await take(replies)
        assert datetime.now(timezone.utc) >= finished + timedelta(seconds=0.035)
        assert ids(req) == (image.stimulus_id, text.stimulus_id)
        assert tuple(p.stimulus_id for p in req.prepared_inputs) == ids(req)
        await until(lambda: not stage._pending)
    finally:
        gate.set()
        await cleanup(stage, adapter)


@pytest.mark.asyncio
async def test_real_preprocessing_persists_slow_image_before_fast_text_in_read_order():
    gate = asyncio.Event()
    class Resolver:
        def resolve(self, media_ref, *, owner_user_id):
            return ResolvedMedia(data=b"image", mime_type="image/png")
    class Vision:
        async def describe_image(self, image_data_uri):
            await gate.wait()
            return "一只白猫"
    class Conversation:
        def __init__(self):
            self.entries = []
        async def append(self, entries):
            self.entries.extend(entries)
            self.entries.sort(key=lambda entry: entry.timestamp)
        def read(self):
            return SimpleNamespace(entries=tuple(self.entries))
    understanding = _Understanding()
    handler = ChatPreprocessingHandler(
        understanding, ImagePreprocessingSkill(Resolver(), Vision()))
    replies = asyncio.Queue()
    class Reply:
        async def handle(self, req, plans):
            replies.put_nowait(req)
            return report(req, consumed=ids(req))
    agent = Agent(character_id="luotianyi", stimulus_router=StimulusRouter([
        (d.StimulusKind.IMAGE_MESSAGE, handler),
        (d.StimulusKind.TEXT_MESSAGE, handler),
        (d.StimulusKind.INTERACTION_DEADLINE, Reply()),
    ]))
    stage, _, adapter, _, _ = await setup(agent, {"response_wait": 0.04})
    stage.context.conversation = Conversation()
    image = stimulus(
        d.ImageMessage, media_ref=d.MediaRef(media_id="image"),
        caption=None, client_msg_id="image")
    text = stimulus(occurred_at=image.occurred_at)
    try:
        stage.stimulus_input_sink.submit(image)
        stage.stimulus_input_sink.submit(text)
        await until(lambda: any(entry.content.text == "你好" for entry in stage.context.conversation.entries))
        await asyncio.sleep(0.06)
        assert replies.empty() and stage._deadline is None
        finished = datetime.now(timezone.utc)
        gate.set()
        req = await take(replies)
        assert datetime.now(timezone.utc) >= finished + timedelta(seconds=0.035)
        assert tuple(item.stimulus_id for item in req.prepared_inputs) == (
            image.stimulus_id, text.stimulus_id)
        snapshot = stage.context.conversation.read()
        assert [entry.content.text for entry in snapshot.entries] == [
            "", "[图片理解]: 一只白猫", "你好"]
    finally:
        gate.set()
        await cleanup(stage, adapter)


@pytest.mark.asyncio
async def test_failed_real_image_preprocessing_drops_only_image_and_keeps_written_text(caplog):
    class Resolver:
        def resolve(self, media_ref, *, owner_user_id):
            raise RuntimeError("image failed")
    class Vision:
        async def describe_image(self, image_data_uri):
            raise AssertionError("vision must not execute")
    handler = ChatPreprocessingHandler(
        _Understanding(), ImagePreprocessingSkill(Resolver(), Vision()))
    replies = asyncio.Queue()
    class Reply:
        async def handle(self, req, plans):
            replies.put_nowait(req)
            return report(req, consumed=ids(req))
    agent = Agent(character_id="luotianyi", stimulus_router=StimulusRouter([
        (d.StimulusKind.IMAGE_MESSAGE, handler),
        (d.StimulusKind.TEXT_MESSAGE, handler),
        (d.StimulusKind.INTERACTION_DEADLINE, Reply()),
    ]))
    stage, _, adapter, _, _ = await setup(agent)
    image = stimulus(
        d.ImageMessage, media_ref=d.MediaRef(media_id="image"),
        caption=None, client_msg_id="image")
    text = stimulus()
    try:
        stage.stimulus_input_sink.submit(image)
        stage.stimulus_input_sink.submit(text)
        req = await take(replies)
        assert ids(req) == (text.stimulus_id,)
        assert len(stage.context.conversation.entries) == 1
        assert stage.context.conversation.entries[0].content.text == "你好"
        assert any("Stage preprocessing failed" in record.message for record in caplog.records)
        await until(lambda: not stage._pending)
    finally:
        await cleanup(stage, adapter)


@pytest.mark.asyncio
@pytest.mark.parametrize("cls,fields,delay", [
    (d.UserTyping, {"text_length": 3}, 10),
    (d.ImageSelectionOpened, {}, 60),
    (d.ImageSelectionClosed, {}, 1),
    (d.UserTyping, {"text_length": 0}, 0),
])
async def test_coordination_changes_wait_but_does_not_cancel_preprocessing(cls, fields, delay):
    gate = asyncio.Event()
    async def handle(req, sink):
        if isinstance(req.stimulus, d.TextMessage):
            await gate.wait()
        return report(req, consumed=ids(req) if isinstance(req.stimulus, d.InteractionDeadline) else ())
    stage, agent, adapter, _, _ = await setup(RecordingAgent(handle), {"response_wait": 1})
    try:
        stage.stimulus_input_sink.submit(stimulus())
        first = await take(agent.requests)
        before = datetime.now(timezone.utc)
        stage.stimulus_input_sink.submit(stimulus(cls, **fields))
        await take(agent.requests)
        assert not first.cancellation.is_cancelled and stage._deadline is None
        assert abs((stage._wait_until - before).total_seconds() - delay) < 0.1
        gate.set()
        if delay:
            await until(lambda: stage._deadline is not None)
            assert stage._deadline >= stage._wait_until
        else:
            req = await take(agent.requests)
            assert isinstance(req.stimulus, d.InteractionDeadline)
    finally:
        gate.set()
        await cleanup(stage, adapter)


@pytest.mark.asyncio
async def test_new_content_cancels_reply_and_reuses_preprocessing_in_new_batch():
    cleanup_entered, cleanup_gate = asyncio.Event(), asyncio.Event()
    attempts, preprocessed = asyncio.Queue(), []
    first_reply = None
    async def handle(req, sink):
        nonlocal first_reply
        if isinstance(req.stimulus, d.TextMessage):
            preprocessed.append(req.stimulus.stimulus_id)
        if isinstance(req.stimulus, d.InteractionDeadline) and req.purpose is d.HandlePurpose.PROCESS:
            attempts.put_nowait(req)
            if first_reply is None:
                first_reply = req
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cleanup_entered.set()
                    await cleanup_gate.wait()
                    # 即使处理器晚返回成功，旧报告也不能清掉输入。
                    return report(req, consumed=ids(req))
            return report(req, consumed=ids(req))
        return report(req)
    stage, _, adapter, _, _ = await setup(RecordingAgent(handle))
    a, b = stimulus(), stimulus()
    try:
        stage.stimulus_input_sink.submit(a)
        old = await take(attempts)
        stage.stimulus_input_sink.submit(b)
        await cleanup_entered.wait()
        await until(lambda: b.stimulus_id in preprocessed)
        assert old.cancellation.reason is d.CancellationReason.SUPERSEDED
        assert attempts.empty()  # 清理完成前不开始新的冲突回复。
        cleanup_gate.set()
        new = await take(attempts)
        assert ids(new) == (a.stimulus_id, b.stimulus_id)
        assert preprocessed == [a.stimulus_id, b.stimulus_id]
        await until(lambda: not stage._pending)
    finally:
        cleanup_gate.set()
        await cleanup(stage, adapter)


@pytest.mark.asyncio
async def test_new_content_cancels_active_and_queued_reply_plans_and_waits_cleanup():
    execution_cleanup, release = asyncio.Event(), asyncio.Event()
    calls, ends = [], []
    async def handle(req, sink):
        if isinstance(req.stimulus, d.InteractionDeadline) and req.purpose is d.HandlePurpose.PROCESS:
            first, second = plan(req), plan(req, ordinal=1)
            await sink.emit(first)
            await sink.emit(second)
            return report(req, consumed=ids(req), plans=(first.plan_id, second.plan_id))
        return report(req)
    async def realize(value, context, sink):
        calls.append((value, context))
        if len(calls) == 1:
            try:
                await asyncio.Event().wait()
            finally:
                execution_cleanup.set()
                await release.wait()
        ends.append(value.plan_id)
        return SimpleNamespace(status=d.ExecutionStatus.COMPLETED, error_code=None)
    stage, _, adapter, _, _ = await setup(RecordingAgent(handle, realize))
    try:
        stage.stimulus_input_sink.submit(stimulus())
        await until(lambda: len(calls) == 1 and len(stage._plans) == 1)
        old_origin = calls[0][0].origin_request_id
        stage.stimulus_input_sink.submit(stimulus())
        await execution_cleanup.wait()
        assert calls[0][1].cancellation.is_cancelled
        await until(lambda: bool(stage._plans))
        assert all(p.origin_request_id != old_origin for p, _ in stage._plans)
        assert len(calls) == 1
        release.set()
        await until(lambda: len(calls) == 3)
        assert all(p.origin_request_id != old_origin for p, _ in calls[1:])
    finally:
        release.set()
        await cleanup(stage, adapter)


@pytest.mark.asyncio
async def test_touch_is_immediate_and_typing_does_not_cancel_reply():
    gate, touch_done = asyncio.Event(), asyncio.Event()
    replies = asyncio.Queue()
    async def handle(req, sink):
        if isinstance(req.stimulus, d.TouchInteraction):
            value = plan(req)
            await sink.emit(value)
            return report(req, plans=(value.plan_id,))
        if isinstance(req.stimulus, d.InteractionDeadline) and req.purpose is d.HandlePurpose.PROCESS:
            replies.put_nowait(req)
            await gate.wait()
            return report(req, consumed=ids(req))
        return report(req)
    async def realize(value, context, sink):
        touch_done.set()
        return SimpleNamespace(status=d.ExecutionStatus.COMPLETED, error_code=None)
    stage, _, adapter, _, _ = await setup(RecordingAgent(handle, realize))
    try:
        stage.stimulus_input_sink.submit(stimulus())
        current = await take(replies)
        stage.stimulus_input_sink.submit(stimulus(d.UserTyping, text_length=3))
        stage.stimulus_input_sink.submit(touch())
        await asyncio.wait_for(touch_done.wait(), 1)
        assert not current.cancellation.is_cancelled
        gate.set()
        await until(lambda: not stage._pending)
    finally:
        gate.set()
        await cleanup(stage, adapter)


@pytest.mark.asyncio
async def test_failed_preprocessing_does_not_block_later_input_and_no_automatic_retry():
    a, b = stimulus(), stimulus()
    calls, replies = [], asyncio.Queue()
    async def handle(req, sink):
        calls.append(req.stimulus.stimulus_id)
        if req.stimulus is a:
            raise RuntimeError("preprocessing failed")
        if isinstance(req.stimulus, d.InteractionDeadline) and req.purpose is d.HandlePurpose.PROCESS:
            replies.put_nowait(req)
            return replace(report(req), request_status=d.HandlingRequestStatus.FAILED, error_code=d.HandlingErrorCode.INTERNAL_ERROR)
        return report(req)
    stage, _, adapter, _, _ = await setup(RecordingAgent(handle))
    try:
        stage.stimulus_input_sink.submit(a)
        stage.stimulus_input_sink.submit(b)
        req = await take(replies)
        assert ids(req) == (b.stimulus_id,)
        await asyncio.sleep(0.06)
        assert replies.empty() and stage._deadline is None
        assert calls.count(a.stimulus_id) == 1
    finally:
        await cleanup(stage, adapter)


@pytest.mark.asyncio
async def test_partial_consumption_keeps_remaining_and_stale_deadline_is_ignored():
    attempts = asyncio.Queue()
    count = 0
    async def handle(req, sink):
        nonlocal count
        if isinstance(req.stimulus, d.InteractionDeadline) and req.purpose is d.HandlePurpose.PROCESS:
            count += 1
            attempts.put_nowait(req)
            return report(req, consumed=ids(req)[:1])
        return report(req)
    stage, _, adapter, _, _ = await setup(RecordingAgent(handle))
    try:
        a, b = stimulus(), stimulus()
        stage.stimulus_input_sink.submit(a)
        stale = stage._schedule_revision
        stage.stimulus_input_sink.submit(b)
        stage._on_deadline(stale)
        assert count == 0
        first, second = await take(attempts), await take(attempts)
        assert ids(first) == (a.stimulus_id, b.stimulus_id) and ids(second) == (b.stimulus_id,)
        await until(lambda: not stage._pending)
    finally:
        await cleanup(stage, adapter)


@pytest.mark.asyncio
async def test_real_agent_context_access_plan_delivery_and_reflection_after_execution():
    release = asyncio.Event()
    events = []
    class Preprocess(ChatPreprocessingHandler):
        async def handle(self, req, plans):
            assert plans.context is stage.context
            events.append("preprocess-and-save")
            return await super().handle(req, plans)
    class Reply:
        async def handle(self, req, plans):
            assert req.prepared_inputs[0].text == "你好"
            events.append("reply")
            accepted = await plans.emit(ActionPlanDraft(source_stimulus_ids=ids(req), actions=plan(req).actions))
            return report(req, consumed=ids(req), plans=(accepted.plan_id,))
    class Reflect(ChatReflectionHandler):
        async def handle(self, req, plans):
            events.append("reflection")
            return await super().handle(req, plans)
    from src.agent.handlers.action.router import ActionRouter
    from src.agent.handlers.stimulus.interaction import InteractionEndingHandler
    class Execute:
        async def realize(self, action, context, outputs):
            events.append("execute")
            await release.wait()
            return d.ActionResult(action_id=action.action_id, status=d.ActionExecutionStatus.COMPLETED,
                error_code=None, irreversible_effect_committed=False, effect_ref=None)
    agent = Agent(character_id="luotianyi", stimulus_router=StimulusRouter([
        (d.StimulusKind.TEXT_MESSAGE, Preprocess(_Understanding())), (d.StimulusKind.INTERACTION_DEADLINE, Reply()),
        (d.StimulusKind.INTERACTION_ENDING, InteractionEndingHandler())], reflection_handler=Reflect()),
        action_router=ActionRouter([(d.ActionKind.SAY, Execute())]))
    stage, _, adapter, _, _ = await setup(agent)
    try:
        stage.stimulus_input_sink.submit(stimulus())
        await until(lambda: "execute" in events)
        assert "reflection" not in events
        release.set()
        await until(lambda: "reflection" in events)
        assert events == ["preprocess-and-save", "reply", "execute", "reflection"]
    finally:
        release.set()
        await cleanup(stage, adapter)
