"""Public handle-input contract; expected behavior comes from domain/handle-input.md."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import get_args
from zoneinfo import ZoneInfo

import pytest

import src.domain.agent as domain
from src.domain.stimulus import SourceChannel, Stimulus as LegacyStimulus, StimulusModality


NOW = datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc)
LOCAL_ZONE = ZoneInfo("Asia/Shanghai")
SNAPSHOTS = ("ChatInteractionSnapshot", "ToyInteractionSnapshot", "WorldInteractionSnapshot")
COORDINATION = ("UserTyping", "ImageSelectionOpened", "ImageSelectionClosed", "InteractionDeadline")


def _public(name):
    # Keep missing target capabilities as explicit assertions, not collection ImportErrors.
    assert name in vars(domain), f"handle-input SPEC public capability not implemented: {name}"
    assert name in domain.__all__, f"handle-input SPEC public export missing: {name}"
    return getattr(domain, name)


def _stimulus(name="TextMessage", stimulus_id="message-1", **overrides):
    fields = dict(
        stimulus_id=stimulus_id, schema_version=1, occurred_at=NOW,
        source=domain.StimulusSource.USER, target_character_ids=("luotianyi",),
        user_id="user-1", ephemeral=False,
    )
    content = {
        "TextMessage": dict(text="  你好  ", client_msg_id="client-1"),
        "ImageMessage": dict(
            media_ref=domain.MediaRef(media_id="image-1"), caption=None, client_msg_id="client-1",
        ),
        "VoiceMessage": dict(media_ref=None, transcript="你好", client_msg_id="client-1"),
        "UserTyping": dict(text_length=4),
        "ImageSelectionOpened": {}, "ImageSelectionClosed": {}, "InteractionDeadline": {},
        "WorldObservation": dict(
            observation_kind=domain.WorldObservationKind(value="citywalk"),
            fact=domain.WorldFact(fact_id="fact-1", summary="到达公园"),
            evidence_refs=(), world_revision=7,
        ),
    }
    fields.update(content[name])
    fields.update(overrides)
    return getattr(domain, name)(**fields)


def _snapshot_fields(name="ChatInteractionSnapshot", **overrides):
    fields = dict(
        interaction_id="interaction-1", interaction_revision=0, user_id="user-1",
        pending_stimuli=(), now=NOW, timezone=LOCAL_ZONE, supported_outputs=frozenset(),
    )
    if name == "ChatInteractionSnapshot":
        fields.update(response_deadline=None, connection_state=_public("ConnectionState").CONNECTED)
    elif name == "ToyInteractionSnapshot":
        fields.update(device_id="device-1", online=True)
    else:
        fields.update(
            world_id="world-1", world_revision=7, activity_id=None, activity_revision=None,
            planning_cycle_id=None, schedule_revision=3,
        )
    fields.update(overrides)
    return fields


def _snapshot(name="ChatInteractionSnapshot", **overrides):
    return _public(name)(**_snapshot_fields(name, **overrides))


def _request_fields(**overrides):
    trigger = _stimulus()
    fields = dict(
        request_id="request-1", stimulus=trigger,
        interaction=_snapshot(pending_stimuli=(trigger,)), cancellation=_public("CancellationToken")(),
    )
    fields.update(overrides)
    return fields


def _request(**overrides):
    return _public("HandleStimulusRequest")(**_request_fields(**overrides))


def _invalid(code, operation):
    error_type = _public("InvalidHandleInputError")
    with pytest.raises(error_type) as caught:
        operation()
    assert isinstance(caught.value, ValueError)
    assert caught.value.code is getattr(_public("HandleInputErrorCode"), code)
    with pytest.raises((AttributeError, TypeError)):
        caught.value.code = "changed"


def _readonly(obj, field, replacement):
    original = getattr(obj, field)
    with pytest.raises((AttributeError, TypeError)):
        setattr(obj, field, replacement)
    assert getattr(obj, field) == original


@pytest.mark.parametrize("name, expected", [
    ("InteractionKind", {"CHAT": "chat", "TOY": "toy", "WORLD": "world"}),
    ("ConnectionState", {"CONNECTED": "connected", "DISCONNECTED": "disconnected"}),
    ("AgentOutputKind", {
        "TEXT_DELTA": "text_delta", "TEXT_FINAL": "text_final", "AUDIO_CHUNK": "audio_chunk",
        "MESSAGE_END": "message_end", "EXPRESSION": "expression", "MOTION": "motion",
    }),
    ("CancellationReason", {"SUPERSEDED": "superseded", "NO_LONGER_NEEDED": "no_longer_needed"}),
    ("HandleInputErrorCode", {
        "CONTRACT_INVALID_INTERACTION": "CONTRACT_INVALID_INTERACTION",
        "CONTRACT_INVALID_HANDLE_REQUEST": "CONTRACT_INVALID_HANDLE_REQUEST",
        "CONTRACT_INVALID_CANCELLATION": "CONTRACT_INVALID_CANCELLATION",
    }),
])
def test_handle_enums_have_only_specified_members_and_wire_values(name, expected):
    """锁定五类枚举的成员及协议值，输出类型不包含已删除的 SONG_STATE。"""
    assert {member.name: member.value for member in _public(name)} == expected


def test_snapshot_union_contains_only_the_three_public_variants():
    """保证公开快照联合只有 Chat、Toy、World，不引入通用或未来变体。"""
    assert set(get_args(_public("InteractionSnapshot"))) == {_public(name) for name in SNAPSHOTS}


def test_removed_snapshot_types_are_not_public():
    """防止被删除的状态对象和通用快照引用重新成为公开依赖。"""
    removed = {"TypingState", "ImageSelectionState", "ContactState", "DeviceOutputLimits", "SnapshotRef"}
    assert removed.isdisjoint(vars(domain))
    assert removed.isdisjoint(domain.__all__)


@pytest.mark.parametrize("name, kind", zip(SNAPSHOTS, ("CHAT", "TOY", "WORLD")))
def test_snapshot_preserves_explicit_facts_without_context_references(name, kind):
    """三种快照直接保存调用方事实，允许空队列/输出且无需上下文引用。"""
    fields = _snapshot_fields(name, interaction_id="  interaction-1  ", user_id=None)
    snapshot = _public(name)(**fields)
    assert snapshot.kind is getattr(_public("InteractionKind"), kind)
    assert {field: getattr(snapshot, field) for field in fields} == fields
    assert not hasattr(snapshot, "conversation_ref")
    assert not hasattr(snapshot, "visible_world_ref")


def test_world_snapshot_carries_observation_content_without_a_snapshot_store():
    """world 事实直接由已有强类型刺激传入，活动和各自修订号可独立表达。"""
    observation = _stimulus("WorldObservation", source=domain.StimulusSource.WORLD, user_id=None)
    snapshot = _snapshot(
        "WorldInteractionSnapshot", pending_stimuli=(observation,), user_id=None,
        interaction_revision=11, activity_id="activity-1", activity_revision=2,
        planning_cycle_id="cycle-1",
    )
    request = _request(stimulus=observation, interaction=snapshot)
    assert request.interaction.pending_stimuli[0].fact.summary == "到达公园"
    assert (snapshot.interaction_revision, snapshot.world_revision, snapshot.activity_revision,
            snapshot.schedule_revision) == (11, 7, 2, 3)
    assert (snapshot.activity_id, snapshot.planning_cycle_id) == ("activity-1", "cycle-1")


def test_new_snapshot_preserves_pending_order_without_changing_the_old_revision():
    """新快照保留 stage 顺序，身份保持稳定而旧修订与队列不被原地更新。"""
    first, second = _stimulus(stimulus_id="later-id"), _stimulus(stimulus_id="earlier-id")
    old = _snapshot(pending_stimuli=(first,), interaction_revision=1)
    new = _snapshot(pending_stimuli=(first, second), interaction_revision=4)
    assert old.interaction_id == new.interaction_id == "interaction-1"
    assert (old.interaction_revision, new.interaction_revision) == (1, 4)
    assert old.pending_stimuli == (first,)
    assert new.pending_stimuli == (first, second)


@pytest.mark.parametrize("name", SNAPSHOTS)
def test_snapshot_fields_and_nested_input_collections_are_immutable(name):
    """冻结快照身份、版本、判别值与集合，禁止借嵌套输入改变旧判断依据。"""
    message = _stimulus()
    snapshot = _snapshot(name, pending_stimuli=(message,))
    for field, value in (("interaction_id", "new"), ("interaction_revision", 2),
                         ("kind", "other"), ("pending_stimuli", ()), ("supported_outputs", frozenset())):
        _readonly(snapshot, field, value)
    with pytest.raises(TypeError):
        snapshot.pending_stimuli[0] = _stimulus(stimulus_id="changed")
    with pytest.raises(AttributeError):
        snapshot.supported_outputs.add(_public("AgentOutputKind").TEXT_FINAL)
    _readonly(snapshot.pending_stimuli[0], "text", "改写消息")


@pytest.mark.parametrize("field, value", [
    ("interaction_id", " "), ("interaction_id", 1), ("interaction_revision", -1),
    ("interaction_revision", True), ("user_id", " "), ("now", NOW.replace(tzinfo=None)),
    ("timezone", "Asia/Shanghai"), ("timezone", timezone.utc),
    ("pending_stimuli", []), ("pending_stimuli", ("message-1",)),
    ("pending_stimuli", ({"stimulus_id": "message-1"},)),
    ("supported_outputs", set()), ("supported_outputs", frozenset({"text_final"})),
    ("response_deadline", NOW.replace(tzinfo=None)), ("connection_state", "connected"),
])
def test_snapshot_rejects_invalid_fields_without_coercion(field, value):
    """对身份、修订、时间、时区、集合及枚举的非法值返回稳定错误，不隐式转换。"""
    factory = _public("ChatInteractionSnapshot")
    fields = _snapshot_fields(**{field: value})
    _invalid("CONTRACT_INVALID_INTERACTION", lambda: factory(**fields))


@pytest.mark.parametrize("name, field, value", [
    ("ToyInteractionSnapshot", "device_id", " "), ("ToyInteractionSnapshot", "online", 1),
    ("WorldInteractionSnapshot", "world_id", ""), ("WorldInteractionSnapshot", "world_revision", -1),
    ("WorldInteractionSnapshot", "schedule_revision", True),
    ("WorldInteractionSnapshot", "planning_cycle_id", " "),
    ("WorldInteractionSnapshot", "activity_id", "activity-without-revision"),
    ("WorldInteractionSnapshot", "activity_revision", 1),
])
def test_variant_rejects_invalid_device_and_world_facts(name, field, value):
    """校验设备/world 专有字段，并拒绝缺少配对活动身份或修订号的快照。"""
    factory = _public(name)
    fields = _snapshot_fields(name, **{field: value})
    _invalid("CONTRACT_INVALID_INTERACTION", lambda: factory(**fields))


@pytest.mark.parametrize("revision", [-1, True])
def test_activity_revision_is_nonnegative_integer_when_activity_exists(revision):
    """已有活动身份时，活动修订也必须是非负整数而非布尔值。"""
    factory = _public("WorldInteractionSnapshot")
    fields = _snapshot_fields("WorldInteractionSnapshot", activity_id="activity-1", activity_revision=revision)
    _invalid("CONTRACT_INVALID_INTERACTION", lambda: factory(**fields))


@pytest.mark.parametrize("name, field", [
    ("ChatInteractionSnapshot", "typing_state"), ("ChatInteractionSnapshot", "image_selection_state"),
    ("ChatInteractionSnapshot", "conversation_ref"), ("ToyInteractionSnapshot", "continuous_contact"),
    ("ToyInteractionSnapshot", "device_output_limits"), ("WorldInteractionSnapshot", "visible_world_ref"),
    ("ChatInteractionSnapshot", "kind"), ("ChatInteractionSnapshot", "context"),
])
def test_snapshot_rejects_deleted_fields_and_caller_supplied_kind(name, field):
    """拒绝旧字段、任意上下文入口和调用方传入的 kind，防止契约扩张。"""
    factory = _public(name)
    fields = _snapshot_fields(name, **{field: None})
    _invalid("CONTRACT_INVALID_INTERACTION", lambda: factory(**fields))


@pytest.mark.parametrize("name", SNAPSHOTS)
def test_snapshot_requires_every_field_as_an_explicit_keyword(name):
    """可空字段也必须显式提供；缺参和位置参数产生稳定领域错误。"""
    factory, fields = _public(name), _snapshot_fields(name)
    for omitted in fields:
        incomplete = {key: value for key, value in fields.items() if key != omitted}
        _invalid("CONTRACT_INVALID_INTERACTION", lambda: factory(**incomplete))
    remaining = {key: value for key, value in fields.items() if key != "interaction_id"}
    _invalid("CONTRACT_INVALID_INTERACTION", lambda: factory("interaction-1", **remaining))


def test_snapshot_rejects_duplicate_pending_ids_even_when_content_differs():
    """pending 按刺激身份去重，既拒绝重复对象也拒绝同 ID 不同内容。"""
    factory = _public("ChatInteractionSnapshot")
    original = _stimulus()
    for duplicate in (original, _stimulus(text="不同内容")):
        fields = _snapshot_fields(pending_stimuli=(original, duplicate))
        _invalid("CONTRACT_INVALID_INTERACTION", lambda: factory(**fields))


@pytest.mark.parametrize("name", COORDINATION)
def test_coordination_signal_cannot_be_pending_content(name):
    """四种协调信号不能混入待结算内容队列。"""
    factory = _public("ChatInteractionSnapshot")
    fields = _snapshot_fields(pending_stimuli=(_stimulus(name),))
    _invalid("CONTRACT_INVALID_INTERACTION", lambda: factory(**fields))


def test_legacy_mapping_stimulus_is_rejected_in_snapshot_and_request():
    """目标输入不接收旧 Mapping 协议，不通过隐式兼容绕过强类型边界。"""
    legacy = LegacyStimulus(source_channel=SourceChannel.WEBSOCKET, modality=StimulusModality.TEXT)
    snapshot_factory = _public("ChatInteractionSnapshot")
    fields = _snapshot_fields(pending_stimuli=(legacy,))
    _invalid("CONTRACT_INVALID_INTERACTION", lambda: snapshot_factory(**fields))
    request_factory = _public("HandleStimulusRequest")
    fields = _request_fields(stimulus=legacy)
    _invalid("CONTRACT_INVALID_HANDLE_REQUEST", lambda: request_factory(**fields))


def test_disconnected_chat_keeps_supported_outputs_and_an_expired_deadline():
    """通道可达性、支持类型和截止时间互不替代，断线不触发构造期取消。"""
    outputs = frozenset({_public("AgentOutputKind").AUDIO_CHUNK, _public("AgentOutputKind").MESSAGE_END})
    deadline = NOW - timedelta(seconds=1)
    snapshot = _snapshot(
        supported_outputs=outputs, connection_state=_public("ConnectionState").DISCONNECTED,
        response_deadline=deadline,
    )
    request = _request(stimulus=_stimulus("InteractionDeadline"), interaction=snapshot)
    assert snapshot.supported_outputs == outputs
    assert snapshot.response_deadline == deadline
    assert snapshot.now == NOW and snapshot.timezone == LOCAL_ZONE
    assert request.cancellation.is_cancelled is False


@pytest.mark.parametrize("name", ("TextMessage", "ImageMessage", "VoiceMessage"))
def test_content_trigger_matches_equal_pending_value_not_object_identity(name):
    """三种消息 trigger 可匹配同值的不同实例，并原样保留请求身份。"""
    trigger, pending = _stimulus(name), _stimulus(name)
    assert trigger is not pending
    request = _request(
        request_id="  request-1  ", stimulus=trigger, interaction=_snapshot(pending_stimuli=(pending,)),
    )
    assert request.request_id == "  request-1  "
    assert request.stimulus == request.interaction.pending_stimuli[0] == trigger


@pytest.mark.parametrize("name", ("TextMessage", "ImageMessage", "VoiceMessage"))
def test_content_trigger_must_exist_in_pending(name):
    """三种内容消息不能只作为 trigger 出现而遗漏在 pending 之外。"""
    factory = _public("HandleStimulusRequest")
    fields = _request_fields(stimulus=_stimulus(name), interaction=_snapshot())
    _invalid("CONTRACT_INVALID_HANDLE_REQUEST", lambda: factory(**fields))


@pytest.mark.parametrize("name", ("TextMessage", "ImageMessage", "VoiceMessage", "WorldObservation"))
def test_matching_trigger_id_with_different_fields_is_rejected(name):
    """trigger 与 pending 同 ID 时比较完整字段，包括正文以外的元数据和 world 刺激。"""
    factory = _public("HandleStimulusRequest")
    trigger, pending = _stimulus(name), _stimulus(name, occurred_at=NOW + timedelta(seconds=1))
    fields = _request_fields(stimulus=trigger, interaction=_snapshot(pending_stimuli=(pending,)))
    _invalid("CONTRACT_INVALID_HANDLE_REQUEST", lambda: factory(**fields))


@pytest.mark.parametrize("name", COORDINATION)
@pytest.mark.parametrize("has_pending", [False, True])
def test_coordination_trigger_works_with_empty_or_populated_pending(name, has_pending):
    """协调信号可以独立触发请求，并保留实际待判断消息而不伪造内容。"""
    pending = (_stimulus(),) if has_pending else ()
    trigger = _stimulus(name, stimulus_id="coordination-1")
    request = _request(stimulus=trigger, interaction=_snapshot(pending_stimuli=pending))
    assert request.stimulus == trigger
    assert request.interaction.pending_stimuli == pending


def test_valid_unusual_combination_is_not_rejected_or_rewritten():
    """不按刺激/交互/用户/输出的常见组合设白名单，也不改写来源或用户身份。"""
    trigger = _stimulus(source=domain.StimulusSource.WORLD, user_id="another-user")
    snapshot = _snapshot(
        "WorldInteractionSnapshot", user_id=None, pending_stimuli=(trigger,),
        supported_outputs=frozenset({_public("AgentOutputKind").EXPRESSION}),
    )
    request = _request(stimulus=trigger, interaction=snapshot)
    assert request.stimulus.source is domain.StimulusSource.WORLD
    assert request.stimulus.user_id == "another-user"
    assert request.interaction.user_id is None


@pytest.mark.parametrize("field, value", [
    ("request_id", " "), ("request_id", 1), ("stimulus", {"text": "你好"}),
    ("interaction", {}), ("cancellation", None),
    ("character_id", "luotianyi"), ("context", {}),
])
def test_request_rejects_invalid_or_extra_fields(field, value):
    """请求拒绝非法身份、字典伪装、缺失令牌以及额外角色/上下文字段。"""
    factory, fields = _public("HandleStimulusRequest"), _request_fields(**{field: value})
    _invalid("CONTRACT_INVALID_HANDLE_REQUEST", lambda: factory(**fields))


def test_request_requires_explicit_keywords_and_is_immutable():
    """四个请求参数都必须显式以关键字提供，构造后不能替换依据或令牌。"""
    factory, fields = _public("HandleStimulusRequest"), _request_fields()
    request = factory(**fields)
    for field in fields:
        incomplete = {key: value for key, value in fields.items() if key != field}
        _invalid("CONTRACT_INVALID_HANDLE_REQUEST", lambda: factory(**incomplete))
        _readonly(request, field, None)
    remaining = {key: value for key, value in fields.items() if key != "request_id"}
    _invalid("CONTRACT_INVALID_HANDLE_REQUEST", lambda: factory("request-1", **remaining))


@pytest.mark.parametrize("reason_name", ("SUPERSEDED", "NO_LONGER_NEEDED"))
def test_request_observes_cancellation_through_the_original_token(reason_name):
    """stage 在传入后取消同一令牌，请求立即观察取消及原因，快照不变。"""
    token = _public("CancellationToken")()
    assert (token.is_cancelled, token.reason) == (False, None)
    request = _request(cancellation=token)
    before = (request.interaction.interaction_revision, request.interaction.pending_stimuli)
    reason = getattr(_public("CancellationReason"), reason_name)
    assert token.cancel(reason) is True
    assert request.cancellation is token
    assert request.cancellation.is_cancelled is True
    assert request.cancellation.reason is reason
    assert (request.interaction.interaction_revision, request.interaction.pending_stimuli) == before


def test_repeated_cancellation_preserves_first_reason():
    """重复取消幂等，后续另一原因也不覆盖首次原因或复活令牌。"""
    token, reasons = _public("CancellationToken")(), _public("CancellationReason")
    assert token.cancel(reasons.SUPERSEDED) is True
    assert token.cancel(reasons.SUPERSEDED) is False
    assert token.cancel(reasons.NO_LONGER_NEEDED) is False
    assert (token.is_cancelled, token.reason) == (True, reasons.SUPERSEDED)


def test_cancelled_token_is_valid_request_input_and_new_tokens_are_independent():
    """预取消请求可以构造；新请求的新令牌不受旧取消影响，旧令牌不被重置。"""
    old_token = _public("CancellationToken")()
    old_token.cancel(_public("CancellationReason").NO_LONGER_NEEDED)
    old_request = _request(cancellation=old_token)
    new_request = _request(request_id="request-2")
    assert old_request.cancellation is old_token
    assert (old_token.is_cancelled, old_token.reason) == (True, _public("CancellationReason").NO_LONGER_NEEDED)
    assert new_request.cancellation is not old_token
    assert (new_request.cancellation.is_cancelled, new_request.cancellation.reason) == (False, None)


def test_token_properties_are_readonly_before_and_after_cancellation():
    """外部不能直接赋值取消状态或原因，只能使用 cancel 进入终态。"""
    token, reasons = _public("CancellationToken")(), _public("CancellationReason")
    _readonly(token, "is_cancelled", True)
    _readonly(token, "reason", reasons.SUPERSEDED)
    token.cancel(reasons.SUPERSEDED)
    _readonly(token, "is_cancelled", False)
    _readonly(token, "reason", None)


@pytest.mark.parametrize("cancelled", [False, True])
@pytest.mark.parametrize("invalid_reason", [None, "superseded", 1])
def test_invalid_cancel_reason_preserves_existing_state(cancelled, invalid_reason):
    """初始和已取消状态都拒绝非法原因，失败调用不能改变状态或覆盖原因。"""
    token = _public("CancellationToken")()
    if cancelled:
        token.cancel(_public("CancellationReason").NO_LONGER_NEEDED)
    before = (token.is_cancelled, token.reason)
    _invalid("CONTRACT_INVALID_CANCELLATION", lambda: token.cancel(invalid_reason))
    assert (token.is_cancelled, token.reason) == before


def test_token_rejects_constructor_arguments_and_missing_cancel_reason():
    """不能通过构造参数注入取消状态，cancel 必须明确提供合法原因。"""
    factory = _public("CancellationToken")
    _invalid("CONTRACT_INVALID_CANCELLATION", lambda: factory(is_cancelled=True))
    _invalid("CONTRACT_INVALID_CANCELLATION", lambda: factory(True))
    token = factory()
    _invalid("CONTRACT_INVALID_CANCELLATION", lambda: token.cancel())
    assert (token.is_cancelled, token.reason) == (False, None)


@pytest.mark.asyncio
async def test_another_task_on_the_same_loop_observes_published_cancellation():
    """同一事件循环中的观察任务能读到同时发布的取消状态和原因，无需真实 Agent。"""
    token, reasons = _public("CancellationToken")(), _public("CancellationReason")
    request = _request(cancellation=token)
    ready, released = asyncio.Event(), asyncio.Event()

    async def observe():
        ready.set()
        await released.wait()
        return request.cancellation.is_cancelled, request.cancellation.reason

    observer = asyncio.create_task(observe())
    try:
        await asyncio.wait_for(ready.wait(), timeout=1)
        token.cancel(reasons.SUPERSEDED)
        released.set()
        assert await asyncio.wait_for(observer, timeout=1) == (True, reasons.SUPERSEDED)
    finally:
        if not observer.done():
            observer.cancel()
        await asyncio.gather(observer, return_exceptions=True)
