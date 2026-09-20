"""首次登录主动欢迎 handler 的失败结算。"""

from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import src.domain.agent as d
from src.agent import Agent
from src.agent.handlers.stimulus import proactive as proactive_module
from src.agent.handlers.stimulus.proactive import FirstLoginHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent_runtime import agent_runtime as runtime_module
from src.agent.skills.expression.prepared_speech import PreparedSpeechCatalog


class PlanSink:
    def __init__(self) -> None:
        self.values: list[d.ActionPlan] = []

    async def emit(self, plan: d.ActionPlan) -> d.PlanReceipt:
        self.values.append(plan)
        return d.PlanReceipt(
            plan_id=plan.plan_id,
            status=d.PlanAcceptanceStatus.ACCEPTED,
        )


def first_login_request(reason: str = "first_login") -> d.HandleStimulusRequest:
    stimulus = d.ProactivePromptDue(
        stimulus_id="first-login",
        schema_version=1,
        occurred_at=datetime.now(timezone.utc),
        source=d.StimulusSource.STAGE,
        target_character_ids=("luotianyi",),
        user_id="user",
        ephemeral=True,
        reason=d.ProactiveReason(value=reason),
        due_at=datetime.now(timezone.utc),
        dedup_key="first-login:user:luotianyi",
        fact_refs=(),
    )
    return d.HandleStimulusRequest(
        request_id="request",
        stimulus=stimulus,
        interaction=d.ChatInteractionSnapshot(
            interaction_id="interaction",
            interaction_revision=1,
            user_id="user",
            pending_stimuli=(),
            now=datetime.now(timezone.utc),
            timezone=ZoneInfo("Asia/Shanghai"),
            supported_outputs=frozenset(
                {
                    d.AgentOutputKind.TEXT_FINAL,
                    d.AgentOutputKind.AUDIO_CHUNK,
                    d.AgentOutputKind.EXPRESSION,
                    d.AgentOutputKind.MESSAGE_END,
                }
            ),
            response_deadline=None,
            connection_state=d.ConnectionState.CONNECTED,
        ),
        cancellation=d.CancellationToken(),
        prepared_inputs=(),
        purpose=d.HandlePurpose.PROCESS,
    )


@pytest.mark.asyncio
async def test_missing_prepared_name_fails_without_silent_skip(monkeypatch):
    # Given: the configured first welcome name does not exist in the manifest.
    logged = []
    logger = SimpleNamespace(error=lambda message, *values: logged.append(message % values))
    monkeypatch.setattr(proactive_module, "get_logger", lambda _: logger)
    handler = FirstLoginHandler(
        prepared_names=("missing",),
        prepared_speech=PreparedSpeechCatalog({}),
    )
    agent = Agent(
        character_id="luotianyi",
        stimulus_router=StimulusRouter(((d.StimulusKind.PROACTIVE_PROMPT_DUE, handler),)),
    )
    sink = PlanSink()
    conversation = SimpleNamespace(append=pytest.fail)
    context = SimpleNamespace(
        identity=SimpleNamespace(
            interaction_id="interaction",
            character_id="luotianyi",
            user_id="user",
        ),
        conversation=conversation,
    )

    # When: the real facade dispatches the first-login stimulus.
    report = await agent.handle_stimulus(first_login_request(), sink, context=context)

    # Then: the entry fails with a stable report and an actionable log.
    assert report.request_status is d.HandlingRequestStatus.FAILED
    assert report.error_code is d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE
    assert report.emitted_plan_ids == ()
    assert sink.values == []
    assert any("missing" in message for message in logged)


@pytest.mark.asyncio
async def test_runtime_injects_configured_names_into_real_handler(runtime_dependencies):
    # Given: AgentRuntime receives the owner-approved first-login config contract.
    kwargs, _ = runtime_dependencies
    kwargs["config"]["proactive"] = {
        "first_login": {"prepared_names": ["welcome_1", "welcome_2"]},
    }

    # When: the production runtime assembles the stimulus router.
    runtime = runtime_module.AgentRuntime(**kwargs)
    try:
        handler = runtime.get_agent()._stimulus_router.resolve(d.StimulusKind.PROACTIVE_PROMPT_DUE)

        # Then: the placeholder is replaced and configured order is retained.
        assert isinstance(handler, FirstLoginHandler)
        assert handler._prepared_names == ("welcome_1", "welcome_2")
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_due_reminder_enters_conversation_and_emits_say_plan():
    # Given: a non-first-login due fact reaches the real proactive handler.
    handler = FirstLoginHandler(
        prepared_names=(),
        prepared_speech=PreparedSpeechCatalog({}),
    )
    agent = Agent(
        character_id="luotianyi",
        stimulus_router=StimulusRouter(((d.StimulusKind.PROACTIVE_PROMPT_DUE, handler),)),
    )
    sink = PlanSink()
    entries = []

    async def append(values) -> None:
        entries.extend(values)

    context = SimpleNamespace(
        identity=SimpleNamespace(
            interaction_id="interaction",
            character_id="luotianyi",
            user_id="user",
        ),
        conversation=SimpleNamespace(append=append),
    )

    # When: Agent handles the reminder through its public handle entrypoint.
    report = await agent.handle_stimulus(
        first_login_request("holiday"),
        sink,
        context=context,
    )

    # Then: cognition persists one agent turn and emits a normal Say plan for realization.
    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert len(entries) == 1
    assert len(sink.values) == 1
    assert len(sink.values[0].actions) == 1
    assert isinstance(sink.values[0].actions[0], d.Say)
