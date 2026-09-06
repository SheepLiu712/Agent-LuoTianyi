"""从运行时取得门面，验证当前空注册版本的可观察契约。"""
from dataclasses import replace
from datetime import datetime, timezone
import inspect
from zoneinfo import ZoneInfo

import pytest

import src.agent as agent_package
import src.domain.agent as d


class RejectUnexpectedEmission:
    async def emit(self, value):
        pytest.fail("入口拒绝不得向 sink 交付任何内容")


def facade(runtime):
    agent = runtime.get_agent("luotianyi")
    assert callable(getattr(agent, "handle_stimulus", None)), "真实 get_agent 返回值缺少 handle_stimulus"
    assert callable(getattr(agent, "realize_action_plan", None)), "真实 get_agent 返回值缺少 realize_action_plan"
    return agent


def request():
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    first = d.TextMessage(
        stimulus_id="m2", schema_version=1, occurred_at=now, source=d.StimulusSource.USER,
        target_character_ids=("luotianyi",), user_id="u", ephemeral=False,
        text="你好", client_msg_id="client-2",
    )
    second = replace(first, stimulus_id="m1", client_msg_id="client-1")
    snapshot = d.ChatInteractionSnapshot(
        interaction_id="i", interaction_revision=3, user_id="u", pending_stimuli=(first, second),
        now=now, timezone=ZoneInfo("UTC"), supported_outputs=frozenset(),
        response_deadline=None, connection_state=d.ConnectionState.CONNECTED,
    )
    return d.HandleStimulusRequest(
        request_id="r", stimulus=first, interaction=snapshot, cancellation=d.CancellationToken(),
    )


def plan_and_context():
    plan = d.ActionPlan(
        plan_id="p", origin_request_id="r", plan_ordinal=1, target_character_id="luotianyi",
        interaction_id="i", basis_interaction_revision=3, source_stimulus_ids=("m2", "m1"),
        actions=(
            d.Say(action_id="a2", content="你好", sound_content=None, prepared_audio_ref=None,
                  tone=d.Tone(value="normal"), expression=None, delivery=d.OutputDelivery.CONVERSATION),
            d.Sing(action_id="a1", song_id="song", segment_id="verse", expression=None),
        ),
    )
    context = d.ExecutionContext(
        execution_id="e", interaction_id="i", current_interaction_revision=3,
        cancellation=d.CancellationToken(),
    )
    return plan, context


def assert_handle_rejection(report, expected, *, cancelled=False):
    assert isinstance(report, d.HandlingReport)
    assert report.request_id == "r"
    assert report.trigger_stimulus_id == "m2"
    assert report.basis_interaction_revision == 3
    assert report.request_status is (d.HandlingRequestStatus.CANCELLED if cancelled else d.HandlingRequestStatus.FAILED)
    assert report.error_code is expected
    assert report.considered_pending_stimulus_ids == ("m2", "m1")
    assert report.retained_pending_stimulus_ids == ("m2", "m1")
    assert report.consumed_pending_stimulus_ids == report.emitted_plan_ids == ()
    assert report.reconsider_at is None
    assert report.retryable is False


def assert_execution_rejection(report, expected, ids=("a2", "a1"), *, cancelled=False):
    assert isinstance(report, d.ExecutionReport)
    assert (report.execution_id, report.plan_id) == ("e", "p")
    assert report.status is (d.ExecutionStatus.CANCELLED if cancelled else d.ExecutionStatus.FAILED)
    assert report.error_code is expected
    assert tuple(item.action_id for item in report.action_results) == ids
    for item in report.action_results:
        assert item.status is d.ActionExecutionStatus.NOT_STARTED
        assert item.error_code is None
        assert item.effect_ref is None
        assert item.irreversible_effect_committed is False
    assert report.output_started is report.irreversible_effect_committed is report.retryable is False


def test_facade_exports_only_agent_and_has_two_documented_business_methods(runtime):
    agent = runtime.get_agent()
    assert set(getattr(agent_package, "__all__", ())) == {"Agent"}
    assert isinstance(agent, agent_package.Agent)
    methods = {name for name, value in inspect.getmembers(type(agent), callable) if not name.startswith("_")}
    assert methods == {"handle_stimulus", "realize_action_plan"}
    for name in methods:
        method = getattr(agent, name)
        assert inspect.iscoroutinefunction(method)
        assert any("\u4e00" <= char <= "\u9fff" for char in (inspect.getdoc(method) or ""))
    for name in ("mind", "capabilities", "database_manager", "conscious", "character_runtime", "main_chat"):
        assert not hasattr(agent, name)


async def test_unregistered_stimulus_preserves_all_pending_without_emission(runtime):
    report = await facade(runtime).handle_stimulus(request(), RejectUnexpectedEmission())
    assert_handle_rejection(report, d.HandlingErrorCode.UNSUPPORTED_STIMULUS)


@pytest.mark.parametrize("location", ["trigger", "pending"])
async def test_handle_checks_target_before_business_routing(runtime, location):
    req = request()
    items = list(req.interaction.pending_stimuli)
    index = 0 if location == "trigger" else 1
    items[index] = replace(items[index], target_character_ids=("miku",))
    req = replace(req, stimulus=items[0], interaction=replace(req.interaction, pending_stimuli=tuple(items)))
    report = await facade(runtime).handle_stimulus(req, RejectUnexpectedEmission())
    assert_handle_rejection(report, d.HandlingErrorCode.CONTRACT_SNAPSHOT_MISMATCH)


@pytest.mark.parametrize("reason", list(d.CancellationReason))
async def test_handle_pre_cancelled_retains_reason_and_pending(runtime, reason):
    req = request()
    req.cancellation.cancel(reason)
    report = await facade(runtime).handle_stimulus(req, RejectUnexpectedEmission())
    assert_handle_rejection(report, None, cancelled=True)
    assert req.cancellation.reason is reason


@pytest.mark.parametrize("change,code", [
    ({}, d.ExecutionErrorCode.UNSUPPORTED_ACTION),
    ({"target_character_id": "miku"}, d.ExecutionErrorCode.CONTRACT_MISMATCH),
    ({"interaction_id": "another"}, d.ExecutionErrorCode.CONTRACT_MISMATCH),
    ({"basis_interaction_revision": 2}, d.ExecutionErrorCode.STALE_INTERACTION),
    ({"basis_interaction_revision": 4}, d.ExecutionErrorCode.STALE_INTERACTION),
])
async def test_execution_preflight_rejects_whole_plan(runtime, change, code):
    plan, context = plan_and_context()
    report = await facade(runtime).realize_action_plan(replace(plan, **change), context, RejectUnexpectedEmission())
    assert_execution_rejection(report, code)


async def test_thinking_plan_is_not_executed_by_agent(runtime):
    plan, context = plan_and_context()
    plan = replace(plan, plan_ordinal=0, actions=(d.StartThinking(action_id="thinking"),))
    report = await facade(runtime).realize_action_plan(plan, context, RejectUnexpectedEmission())
    assert_execution_rejection(report, d.ExecutionErrorCode.UNSUPPORTED_ACTION, ("thinking",))


@pytest.mark.parametrize("reason", list(d.CancellationReason))
async def test_execution_pre_cancelled_has_no_started_actions(runtime, reason):
    plan, context = plan_and_context()
    context.cancellation.cancel(reason)
    report = await facade(runtime).realize_action_plan(plan, context, RejectUnexpectedEmission())
    assert_execution_rejection(report, d.ExecutionErrorCode.CANCELLED, cancelled=True)
    assert context.cancellation.reason is reason


@pytest.mark.parametrize("side", ["handle", "realize"])
async def test_cached_facade_rejects_work_after_runtime_shutdown(runtime, side):
    agent = facade(runtime)
    await runtime.shutdown()
    assert runtime.get_agent("luotianyi") is agent
    if side == "handle":
        report = await agent.handle_stimulus(request(), RejectUnexpectedEmission())
        assert_handle_rejection(report, d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE)
    else:
        plan, context = plan_and_context()
        report = await agent.realize_action_plan(plan, context, RejectUnexpectedEmission())
        assert_execution_rejection(report, d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE)


@pytest.mark.parametrize("bad_argument", ["request", "plan_sink", "plan", "context", "output_sink"])
async def test_wrong_top_level_value_is_call_error(runtime, bad_argument):
    agent = facade(runtime)
    with pytest.raises(TypeError):
        if bad_argument in ("request", "plan_sink"):
            await agent.handle_stimulus(
                {} if bad_argument == "request" else request(),
                {} if bad_argument == "plan_sink" else RejectUnexpectedEmission(),
            )
        else:
            plan, context = plan_and_context()
            await agent.realize_action_plan(
                {} if bad_argument == "plan" else plan,
                {} if bad_argument == "context" else context,
                {} if bad_argument == "output_sink" else RejectUnexpectedEmission(),
            )
