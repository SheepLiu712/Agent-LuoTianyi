"""动态观察事实的 Agent 侧回复决策、评论发布与记忆写入。"""
import asyncio
from datetime import datetime, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import src.domain.agent as d
from src.agent.handlers.action.dynamic_reply import ReplyDynamicHandler
from src.agent.handlers.stimulus.dynamic_observed import DynamicObservedHandler
from src.agent.processing.plan_emitter import PlanEmitter
from src.agent.skills.cognitive.dynamic_topic_memory import DynamicTopicMemorySkill
from src.agent.skills.expression.dynamic_reply import DynamicReplySkill

CHARACTER_ID = "luotianyi"
USER_ID = "user-1"
REPLY_BODY = "我看到你坚持下来了，辛苦啦。"


class FakeReplier:
    def __init__(self, *, available=True, post_reply=REPLY_BODY,
                 comment_decision=None, fail=False):
        self.available = available
        self.post_reply = post_reply
        self.comment_decision = comment_decision or {"should_reply": True, "reply": REPLY_BODY}
        self.fail = fail
        self.post_items = []
        self.comment_items = []

    def ensure_llm(self) -> bool:
        return self.available

    async def generate_reply_for_post(self, item, *, character_name=None):
        if self.fail:
            raise RuntimeError("reply unavailable")
        self.post_items.append(item)
        return self.post_reply

    async def generate_reply_for_comment(self, item, *, character_name=None):
        if self.fail:
            raise RuntimeError("reply unavailable")
        self.comment_items.append(item)
        return self.comment_decision


class FakeDynamics:
    def __init__(self, replier: FakeReplier, *, publish_ok=True, comment_id="comment-1"):
        self.replier = replier
        self.publish_ok = publish_ok
        self.comment_id = comment_id
        self.published = []

    def publish_agent_comment(self, **kwargs):
        self.published.append(kwargs)
        if not self.publish_ok:
            return False, "comment rejected", None
        return True, "created", {"id": self.comment_id}


class FakeMemory:
    def __init__(self, *, items=None, fail=False):
        self.items = items if items is not None else [
            {"memory_type": "user_memory", "content": "用户坚持下来了", "status": "written"},
        ]
        self.fail = fail
        self.calls = []

    async def write_topic_memories(self, *, user_id, history, current_dialogue,
                                   related_memories, commit=True):
        self.calls.append({
            "user_id": user_id, "history": history,
            "current_dialogue": current_dialogue, "commit": commit,
        })
        if self.fail:
            raise RuntimeError("memory unavailable")
        return {"payload": {"user_memory": []}, "items": self.items}


class Sink:
    def __init__(self):
        self.plans = []

    async def emit(self, plan):
        self.plans.append(plan)
        return d.PlanReceipt(plan_id=plan.plan_id, status=d.PlanAcceptanceStatus.ACCEPTED)


def _message(message_id: str, *, text: str, actor_id: str = USER_ID,
             name: str = "小明", parent: str | None = None) -> d.DynamicMessage:
    return d.DynamicMessage(
        message_id=message_id, parent_message_id=parent,
        author_ref=d.ActorRef(actor_id=actor_id, display_name=name),
        text=text, media_refs=(),
    )


def _observation(*, target_kind: d.DynamicTargetKind = d.DynamicTargetKind.POST,
                 target_id: str | None = None,
                 messages: tuple[d.DynamicMessage, ...] | None = None) -> d.DynamicObserved:
    dynamic_id = "dyn-1"
    messages = messages or (_message(dynamic_id, text="今天其实有点紧张，不过也算坚持下来了。"),)
    return d.DynamicObserved(
        stimulus_id=str(uuid4()), schema_version=1, occurred_at=datetime.now(timezone.utc),
        source=d.StimulusSource.WORLD, target_character_ids=(CHARACTER_ID,), user_id=None,
        ephemeral=False, dynamic_id=dynamic_id,
        target_message_id=target_id or dynamic_id, target_kind=target_kind,
        messages=messages, revision=len(messages),
    )


def _request(fact: d.DynamicObserved) -> d.HandleStimulusRequest:
    return d.HandleStimulusRequest(
        request_id="req", stimulus=fact,
        interaction=d.WorldInteractionSnapshot(
            interaction_id="wi", interaction_revision=1, user_id=None, pending_stimuli=(fact,),
            now=fact.occurred_at, timezone=ZoneInfo("UTC"), supported_outputs=frozenset(),
            world_id="default", world_revision=fact.revision, activity_id=None,
            activity_revision=None, planning_cycle_id=None, schedule_revision=0,
        ),
        cancellation=d.CancellationToken(),
    )


def _handler(replier: FakeReplier, *, memory: FakeMemory | None = None,
             publish_ok: bool = True):
    dynamics = FakeDynamics(replier, publish_ok=publish_ok)
    reply = DynamicReplySkill(dynamics, character_id=CHARACTER_ID, character_name="洛天依")
    memory = memory if memory is not None else FakeMemory()
    return DynamicObservedHandler(
        CHARACTER_ID, reply, DynamicTopicMemorySkill(memory),
    ), dynamics, memory, reply


def test_post_observation_delivers_reply_and_publishes_comment():
    """原帖观察生成回复计划，经回复处理器提交评论效果。"""
    replier = FakeReplier()
    handler, dynamics, memory, reply = _handler(replier)
    fact = _observation()
    request = _request(fact)
    sink = Sink()

    handling = asyncio.run(
        handler.handle(request, PlanEmitter(character_id=CHARACTER_ID, request=request, sink=sink))
    )

    assert handling.request_status is d.HandlingRequestStatus.COMPLETED
    assert len(sink.plans) == 1
    action = sink.plans[0].actions[0]
    assert isinstance(action, d.ReplyDynamic)
    assert action.target.dynamic_id == "dyn-1"
    assert action.target.parent_comment_id is None
    assert action.owner_user_id == USER_ID
    assert action.body == REPLY_BODY
    assert replier.post_items[0]["content"].startswith("今天其实有点紧张")
    assert memory.calls[0]["user_id"] == USER_ID

    first_plan = sink.plans[0]
    action_result = asyncio.run(
        ReplyDynamicHandler(CHARACTER_ID, reply).realize(
            action,
            d.ExecutionContext(execution_id="e", interaction_id="wi",
                               current_interaction_revision=1, cancellation=d.CancellationToken()),
            None,
        )
    )

    assert first_plan.actions[0].action_id == action.action_id
    assert action_result.status is d.ActionExecutionStatus.COMPLETED
    assert action_result.effect_ref == d.EffectRef(
        kind=d.EffectKind.DYNAMIC_COMMENT, effect_id="comment-1",
    )
    assert dynamics.published[0]["parent_comment_id"] is None
    assert dynamics.published[0]["owner_user_id"] == USER_ID


def test_comment_observation_can_be_ignored_explicitly():
    """评论判断为不回复时只结算消费，不产生计划。"""
    replier = FakeReplier(comment_decision={"should_reply": False, "reply": ""})
    handler, _, memory, _ = _handler(replier)
    fact = _observation(
        target_kind=d.DynamicTargetKind.COMMENT, target_id="comment-9",
        messages=(
            _message("dyn-1", text="今天其实有点紧张，不过也算坚持下来了。"),
            _message("comment-9", text="加油，慢慢来。", parent="dyn-1"),
        ),
    )
    request = _request(fact)
    sink = Sink()

    handling = asyncio.run(
        handler.handle(request, PlanEmitter(character_id=CHARACTER_ID, request=request, sink=sink))
    )

    assert handling.request_status is d.HandlingRequestStatus.COMPLETED
    assert handling.emitted_plan_ids == ()
    assert fact.stimulus_id in handling.consumed_pending_stimulus_ids
    assert sink.plans == []
    assert memory.calls[0]["current_dialogue"] == "user: 加油，慢慢来。"


def test_comment_observation_replies_to_comment_parent():
    """回复评论时 parent_comment_id 指向该评论，归属该评论作者。"""
    replier = FakeReplier()
    handler, _, _, _ = _handler(replier)
    fact = _observation(
        target_kind=d.DynamicTargetKind.COMMENT, target_id="comment-9",
        messages=(
            _message("dyn-1", text="今天其实有点紧张，不过也算坚持下来了。"),
            _message("comment-9", text="加油，慢慢来。", actor_id="user-2", parent="dyn-1"),
        ),
    )
    request = _request(fact)
    sink = Sink()

    asyncio.run(
        handler.handle(request, PlanEmitter(character_id=CHARACTER_ID, request=request, sink=sink))
    )

    action = sink.plans[0].actions[0]
    assert action.target.parent_comment_id == "comment-9"
    assert action.owner_user_id == "user-2"


def test_existing_character_reply_is_not_published_again():
    """线程中已存在角色回复时不再重复发布评论。"""
    replier = FakeReplier()
    handler, _, _, _ = _handler(replier)
    fact = _observation(
        target_kind=d.DynamicTargetKind.COMMENT, target_id="comment-9",
        messages=(
            _message("dyn-1", text="今天其实有点紧张。"),
            _message("comment-9", text="加油，慢慢来。", actor_id="user-2", parent="dyn-1"),
            _message("comment-10", text="谢谢你呀。", actor_id=CHARACTER_ID,
                     name="洛天依", parent="comment-9"),
        ),
    )
    request = _request(fact)
    sink = Sink()

    handling = asyncio.run(
        handler.handle(request, PlanEmitter(character_id=CHARACTER_ID, request=request, sink=sink))
    )

    assert handling.request_status is d.HandlingRequestStatus.COMPLETED
    assert handling.emitted_plan_ids == ()
    assert sink.plans == []
    assert replier.comment_items == []


def test_unavailable_reply_model_fails_without_faking_success():
    """回复模型不可用时处理明确失败，记忆仍然写入。"""
    replier = FakeReplier(available=False)
    handler, _, memory, _ = _handler(replier)
    fact = _observation()
    request = _request(fact)
    sink = Sink()

    handling = asyncio.run(
        handler.handle(request, PlanEmitter(character_id=CHARACTER_ID, request=request, sink=sink))
    )

    assert handling.request_status is d.HandlingRequestStatus.FAILED
    assert handling.error_code is d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE
    assert handling.emitted_plan_ids == ()
    assert sink.plans == []
    assert len(memory.calls) == 1


def test_memory_failure_does_not_block_reply():
    """记忆写入失败只记录，回复计划照常交付。"""
    replier = FakeReplier()
    handler, _, _, _ = _handler(replier, memory=FakeMemory(fail=True))
    fact = _observation()
    request = _request(fact)
    sink = Sink()

    handling = asyncio.run(
        handler.handle(request, PlanEmitter(character_id=CHARACTER_ID, request=request, sink=sink))
    )

    assert handling.request_status is d.HandlingRequestStatus.COMPLETED
    assert len(handling.emitted_plan_ids) == 1
    assert len(sink.plans) == 1


def test_reply_publish_failure_is_reported_without_effect():
    """评论发布失败时返回稳定错误码且不声称已提交效果。"""
    replier = FakeReplier()
    handler, _, memory, reply = _handler(replier, publish_ok=False)
    fact = _observation()
    request = _request(fact)
    sink = Sink()
    asyncio.run(
        handler.handle(request, PlanEmitter(character_id=CHARACTER_ID, request=request, sink=sink))
    )

    action = sink.plans[0].actions[0]
    action_result = asyncio.run(
        ReplyDynamicHandler(CHARACTER_ID, reply).realize(
            action,
            d.ExecutionContext(execution_id="e", interaction_id="wi",
                               current_interaction_revision=1, cancellation=d.CancellationToken()),
            None,
        )
    )

    assert action_result.status is d.ActionExecutionStatus.FAILED
    assert action_result.effect_ref is None
    assert action_result.irreversible_effect_committed is False
    assert len(memory.calls) == 1
