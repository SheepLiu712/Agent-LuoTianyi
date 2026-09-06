"""通过公开构造器验证 realization 的值契约，不冒充运行时投递验收。"""

import inspect
from datetime import date, datetime
from enum import Enum
from typing import get_type_hints

import pytest
import src.domain.agent as domain


ENUMS = {
    "ActionKind": "start_thinking say sing write_diary publish_dynamic reply_dynamic request_song_learning",
    "OutputDelivery": "conversation ephemeral_reaction",
    "Visibility": "global private",
    "PlanAcceptanceStatus": "accepted already_accepted",
    "OutputAcceptanceStatus": "accepted already_accepted",
    "AudioFraming": "complete_file file_fragment",
    "MessageEndStatus": "completed failed cancelled",
    "ExecutionStatus": "completed failed cancelled",
    "ActionExecutionStatus": "completed already_completed cancelled failed not_started",
    "EffectKind": "dynamic_post dynamic_comment song_learning_job",
    "AudioErrorCode": "EMPTY_AUDIO GENERATION_FAILED",
    "SinkRejectionCode": "IDENTITY_MISMATCH CONTENT_CONFLICT STALE_INTERACTION UNSUPPORTED_OUTPUT SINK_CLOSED BACKPRESSURE_TIMEOUT",
    "ExecutionErrorCode": "CONTRACT_MISMATCH UNSUPPORTED_ACTION UNSUPPORTED_OUTPUT STALE_INTERACTION SINK_CLOSED BACKPRESSURE_TIMEOUT DEPENDENCY_UNAVAILABLE PROVIDER_TIMEOUT AUDIO_EMPTY AUDIO_GENERATION_FAILED CANCELLED INTERNAL_ERROR",
    "RealizationContractErrorCode": "CONTRACT_INVALID_ACTION CONTRACT_INVALID_PLAN CONTRACT_INVALID_EXECUTION_CONTEXT CONTRACT_INVALID_OUTPUT CONTRACT_INVALID_RECEIPT CONTRACT_INVALID_EXECUTION_REPORT CONTRACT_INVALID_VALUE",
}
CASES = (
    "Tone ChangeExpression DynamicReplyTarget DynamicSource StartThinking Say Sing WriteDiary "
    "PublishDynamic ReplyDynamic RequestSongLearning ActionPlan ExecutionContext PlanReceipt "
    "OutputReceipt TextFinalOutput AudioChunkOutput MessageEndOutput ExpressionOutput EffectRef "
    "ActionResult ExecutionReport"
).split()


def public(name):
    assert name in domain.__all__, f"尚未实现公开契约：{name}"
    return getattr(domain, name)


def member(name, value):
    return public(name)[value]


def fields(name):
    if name == "Tone":
        return dict(value="normal")
    if name == "ChangeExpression":
        return dict(expression_id="微笑脸")
    if name == "DynamicReplyTarget":
        return dict(dynamic_id="post", parent_comment_id=None)
    if name == "DynamicSource":
        return dict(source_type="citywalk", source_id="walk-1")
    if name == "EffectRef":
        return dict(kind=member("EffectKind", "DYNAMIC_POST"), effect_id="post")
    if name == "ActionResult":
        return dict(action_id="a", status=member("ActionExecutionStatus", "COMPLETED"),
                    error_code=None, irreversible_effect_committed=False, effect_ref=None)
    if name == "ExecutionReport":
        return dict(execution_id="e", plan_id="p", status=member("ExecutionStatus", "COMPLETED"),
                    action_results=(make("ActionResult"),), output_started=True,
                    error_code=None, retryable=False)
    if name == "ActionPlan":
        return dict(plan_id="p", origin_request_id="r", plan_ordinal=0, target_character_id="c",
                    interaction_id="i", basis_interaction_revision=0,
                    source_stimulus_ids=("m2", "m1"), actions=(make("Say"),))
    if name == "ExecutionContext":
        return dict(execution_id="e", interaction_id="i", current_interaction_revision=0,
                    cancellation=domain.CancellationToken())
    if name == "PlanReceipt":
        return dict(plan_id="p", status=member("PlanAcceptanceStatus", "ACCEPTED"))
    if name == "OutputReceipt":
        return dict(execution_id="e", sequence_no=0,
                    status=member("OutputAcceptanceStatus", "ACCEPTED"))
    if name.endswith("Output"):
        base = dict(interaction_id="i", execution_id="e", action_id="a", sequence_no=0,
                    delivery=member("OutputDelivery", "CONVERSATION"))
        extra = {
            "TextFinalOutput": lambda: dict(text="你好"),
            "AudioChunkOutput": lambda: dict(data=b"encoded", framing=member("AudioFraming", "COMPLETE_FILE")),
            "MessageEndOutput": lambda: dict(status=member("MessageEndStatus", "COMPLETED"), error_code=None),
            "ExpressionOutput": lambda: dict(expression=make("ChangeExpression")),
        }
        return base | extra[name]()
    base = dict(action_id="a")
    extra = {
        "StartThinking": lambda: {},
        "Say": lambda: dict(content="  你好  ", sound_content="你好", prepared_audio_ref=None,
                            tone=make("Tone"), expression=make("ChangeExpression"),
                            delivery=member("OutputDelivery", "CONVERSATION")),
        "Sing": lambda: dict(song_id="song", segment_id="verse", expression=None),
        "WriteDiary": lambda: dict(owner_user_id="u", local_date=date(2026, 9, 6), body="日记"),
        "PublishDynamic": lambda: dict(body="动态", media_refs=(), visibility=member("Visibility", "GLOBAL"),
                                       owner_user_id=None, source=make("DynamicSource"), allow_comment=True),
        "ReplyDynamic": lambda: dict(target=make("DynamicReplyTarget"), owner_user_id="u", body="评论"),
        "RequestSongLearning": lambda: dict(song_id="song", dedup_key="learn-song"),
    }
    return base | extra[name]()


def make(name, **changes):
    return public(name)(**(fields(name) | changes))


def error_code(name):
    if name in "StartThinking Say Sing WriteDiary PublishDynamic ReplyDynamic RequestSongLearning".split():
        return "CONTRACT_INVALID_ACTION"
    if name.endswith("Output"):
        return "CONTRACT_INVALID_OUTPUT"
    if name.endswith("Receipt"):
        return "CONTRACT_INVALID_RECEIPT"
    return {"ActionPlan": "CONTRACT_INVALID_PLAN", "ExecutionContext": "CONTRACT_INVALID_EXECUTION_CONTEXT",
            "ActionResult": "CONTRACT_INVALID_EXECUTION_REPORT", "ExecutionReport": "CONTRACT_INVALID_EXECUTION_REPORT"}.get(name, "CONTRACT_INVALID_VALUE")


def invalid(name, **changes):
    args = fields(name) | changes
    factory = public(name)
    with pytest.raises(public("InvalidRealizationContractError")) as caught:
        factory(**args)
    assert caught.value.code is member("RealizationContractErrorCode", error_code(name))


@pytest.mark.parametrize("name,values", ENUMS.items())
def test_enum_wire_values(name, values):
    assert {item.name: item.value for item in public(name)} == {v.upper(): v for v in values.split()}


@pytest.mark.parametrize("name", CASES)
def test_values_preserve_explicit_fields_and_are_immutable(name):
    args = fields(name)
    value = public(name)(**args)
    assert value == public(name)(**args)
    for field, original in args.items():
        assert getattr(value, field) == original
        with pytest.raises((AttributeError, TypeError)):
            setattr(value, field, None)


@pytest.mark.parametrize("name", CASES)
def test_keyword_only_required_fields_and_extra_arguments_have_stable_errors(name):
    args = fields(name)
    factory, failure = public(name), public("InvalidRealizationContractError")
    attempts = [({**args, "payload": {}}, ()), (args, ("extra",))]
    attempts += [({k: v for k, v in args.items() if k != missing}, ()) for missing in args]
    for kwargs, positional in attempts:
        with pytest.raises(failure) as caught:
            factory(*positional, **kwargs)
        assert caught.value.code is member("RealizationContractErrorCode", error_code(name))


@pytest.mark.parametrize("name", CASES)
def test_wrong_field_types_are_rejected(name):
    for field, value in fields(name).items():
        invalid(name, **{field: object()})
        if isinstance(value, str):
            invalid(name, **{field: "   "})
        elif type(value) is int:
            invalid(name, **{field: -1})
            invalid(name, **{field: True})
        elif isinstance(value, tuple):
            invalid(name, **{field: list(value)})


def test_abstract_bases_and_fixed_kinds():
    for name in ("Action", "AgentOutput"):
        assert inspect.isabstract(public(name))
        with pytest.raises(TypeError):
            public(name)()
    for name, kind in {"StartThinking": "START_THINKING", "Say": "SAY", "Sing": "SING",
                       "WriteDiary": "WRITE_DIARY", "PublishDynamic": "PUBLISH_DYNAMIC",
                       "ReplyDynamic": "REPLY_DYNAMIC", "RequestSongLearning": "REQUEST_SONG_LEARNING",
                       "TextFinalOutput": "TEXT_FINAL", "AudioChunkOutput": "AUDIO_CHUNK",
                       "MessageEndOutput": "MESSAGE_END", "ExpressionOutput": "EXPRESSION"}.items():
        value = make(name)
        assert value.kind.name == kind
        invalid(name, kind=value.kind)


def test_output_end_kind_replaces_audio_end_and_is_accepted_by_snapshot():
    kind = domain.AgentOutputKind
    assert {v.value for v in kind} == {"text_delta", "text_final", "audio_chunk", "message_end", "expression", "motion"}
    from datetime import timezone
    from zoneinfo import ZoneInfo
    snapshot = domain.ChatInteractionSnapshot(
        interaction_id="i", interaction_revision=0, user_id=None, pending_stimuli=(),
        now=datetime.now(timezone.utc), timezone=ZoneInfo("UTC"), supported_outputs=frozenset({kind.MESSAGE_END}),
        response_deadline=None, connection_state=domain.ConnectionState.CONNECTED)
    assert kind.MESSAGE_END in snapshot.supported_outputs


def test_say_text_only_and_prepared_ephemeral_audio_are_distinct_modes():
    assert make("Say", sound_content=None).content == "  你好  "
    audio = domain.MediaRef(media_id="media")
    reaction = make("Say", content="", sound_content=None, prepared_audio_ref=audio,
                    delivery=member("OutputDelivery", "EPHEMERAL_REACTION"))
    assert reaction.prepared_audio_ref is audio
    invalid("Say", prepared_audio_ref=audio)
    invalid("Say", content="", sound_content=None)
    invalid("Say", sound_content=" ")


def test_private_publish_requires_owner_and_typed_references():
    private = member("Visibility", "PRIVATE")
    invalid("PublishDynamic", visibility=private)
    assert make("PublishDynamic", visibility=private, owner_user_id="u").owner_user_id == "u"
    invalid("PublishDynamic", media_refs=(domain.EvidenceRef(evidence_id="m"),))
    invalid("WriteDiary", local_date=datetime(2026, 9, 6))
    invalid("DynamicReplyTarget", parent_comment_id=" ")


def test_plan_preserves_order_and_thinking_is_an_isolated_first_plan():
    first, second = make("Say", action_id="z"), make("Sing", action_id="a")
    assert make("ActionPlan", actions=(first, second)).actions == (first, second)
    invalid("ActionPlan", actions=())
    invalid("ActionPlan", actions=(first, first))
    invalid("ActionPlan", source_stimulus_ids=("x", "x"))
    invalid("ActionPlan", source_stimulus_ids=("",))
    thinking = make("StartThinking")
    assert make("ActionPlan", actions=(thinking,), source_stimulus_ids=()).actions == (thinking,)
    invalid("ActionPlan", actions=(thinking,), plan_ordinal=1)
    invalid("ActionPlan", actions=(thinking, second))


def test_execution_context_observes_original_live_token():
    token = domain.CancellationToken()
    context = make("ExecutionContext", cancellation=token)
    assert context.cancellation is token
    token.cancel(domain.CancellationReason.SUPERSEDED)
    assert context.cancellation.reason is domain.CancellationReason.SUPERSEDED


@pytest.mark.parametrize("status", ["COMPLETED", "CANCELLED", "FAILED"])
def test_message_end_carries_explicit_status_without_requiring_audio(status):
    code = member("AudioErrorCode", "EMPTY_AUDIO") if status == "FAILED" else None
    end = make("MessageEndOutput", status=member("MessageEndStatus", status), error_code=code)
    assert end.error_code is code
    invalid("MessageEndOutput", status=member("MessageEndStatus", status),
            error_code=None if code else member("AudioErrorCode", "GENERATION_FAILED"))


def test_audio_content_and_framing_are_preserved_without_decoding():
    for framing in public("AudioFraming"):
        assert make("AudioChunkOutput", framing=framing).data == b"encoded"
    for data in (b"", bytearray(b"x"), domain.MediaRef(media_id="m")):
        invalid("AudioChunkOutput", data=data)


def test_protocol_signatures_and_success_or_exception_contract():
    for name, argument, value, receipt in (
        ("ActionPlanSink", "plan", "ActionPlan", "PlanReceipt"),
        ("AgentOutputSink", "output", "AgentOutput", "OutputReceipt"),
    ):
        method = public(name).emit
        assert inspect.iscoroutinefunction(method)
        assert list(inspect.signature(method).parameters) == ["self", argument]
        hints = get_type_hints(method)
        assert hints[argument] is public(value)
        assert hints["return"] is public(receipt)
    failure = public("SinkRejectedError")("closed", code=member("SinkRejectionCode", "SINK_CLOSED"))
    assert failure.code is member("SinkRejectionCode", "SINK_CLOSED")
    with pytest.raises(AttributeError):
        failure.code = None
    assert not isinstance(failure, public("InvalidRealizationContractError"))


def test_report_preserves_partial_effect_and_derives_aggregate():
    effect = make("EffectRef")
    done = make("ActionResult", irreversible_effect_committed=True, effect_ref=effect)
    failed = make("ActionResult", action_id="b", status=member("ActionExecutionStatus", "FAILED"),
                  error_code=member("ExecutionErrorCode", "PROVIDER_TIMEOUT"))
    pending = make("ActionResult", action_id="c", status=member("ActionExecutionStatus", "NOT_STARTED"))
    report = make("ExecutionReport", status=member("ExecutionStatus", "FAILED"),
                  action_results=(done, failed, pending), error_code=failed.error_code, retryable=True)
    assert report.irreversible_effect_committed is True
    assert make("ExecutionReport").irreversible_effect_committed is False
    with pytest.raises(AttributeError):
        report.irreversible_effect_committed = False
    invalid("ExecutionReport", irreversible_effect_committed=True)
    invalid("ExecutionReport", action_results=(done, done))
    invalid("ExecutionReport", action_results=())
    invalid("ExecutionReport", action_results=(pending, done))
    invalid("ExecutionReport", action_results=(failed, done), status=report.status, error_code=failed.error_code)
    invalid("ExecutionReport", action_results=(failed,), status=report.status,
            error_code=member("ExecutionErrorCode", "INTERNAL_ERROR"))


@pytest.mark.parametrize("status", ["COMPLETED", "ALREADY_COMPLETED", "NOT_STARTED", "FAILED", "CANCELLED"])
def test_action_status_error_and_effect_rules(status):
    code = member("ExecutionErrorCode", "INTERNAL_ERROR") if status == "FAILED" else (
        member("ExecutionErrorCode", "CANCELLED") if status == "CANCELLED" else None)
    args = dict(status=member("ActionExecutionStatus", status), error_code=code)
    assert make("ActionResult", **args).error_code is code
    invalid("ActionResult", **(args | {"error_code": None if code else member("ExecutionErrorCode", "INTERNAL_ERROR")}))
    invalid("ActionResult", **(args | {"effect_ref": make("EffectRef")}))
    if status == "NOT_STARTED":
        invalid("ActionResult", **args, irreversible_effect_committed=True)


@pytest.mark.parametrize("status", ["FAILED", "CANCELLED"])
def test_execution_can_stop_before_first_action(status):
    result = make("ActionResult", status=member("ActionExecutionStatus", "NOT_STARTED"))
    code = member("ExecutionErrorCode", "CANCELLED" if status == "CANCELLED" else "SINK_CLOSED")
    assert make("ExecutionReport", status=member("ExecutionStatus", status), action_results=(result,),
                error_code=code, output_started=False).output_started is False
    invalid("ExecutionReport", action_results=(result,))


def test_enum_strings_and_foreign_enum_are_not_typed_values():
    class Other(str, Enum):
        COMPLETED = "completed"
    for value in ("completed", Other.COMPLETED):
        invalid("ActionResult", status=value)
    invalid("PlanReceipt", status=member("OutputAcceptanceStatus", "ACCEPTED"))
    invalid("ExecutionReport", status=member("MessageEndStatus", "COMPLETED"))


def test_construction_failure_code_is_readonly():
    error = public("InvalidRealizationContractError")("bad", code=member("RealizationContractErrorCode", "CONTRACT_INVALID_PLAN"))
    assert isinstance(error, ValueError)
    with pytest.raises(AttributeError):
        error.code = None
