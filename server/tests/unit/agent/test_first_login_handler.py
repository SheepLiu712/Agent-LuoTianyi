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
from src.agent.skills.cognitive import ReplyDraft
from src.agent.skills.expression.prepared_speech import PreparedSpeechCatalog
from src.agent_runtime import agent_runtime as runtime_module


class PlanSink:
    def __init__(self) -> None:
        self.values: list[d.ActionPlan] = []

    async def emit(self, plan: d.ActionPlan) -> d.PlanReceipt:
        self.values.append(plan)
        return d.PlanReceipt(
            plan_id=plan.plan_id,
            status=d.PlanAcceptanceStatus.ACCEPTED,
        )


class Composer:
    def __init__(self, drafts=()):
        self.drafts = tuple(drafts)
        self.calls = []

    async def compose(self, invocation, **kwargs):
        self.calls.append({"invocation": invocation, **kwargs})
        return self.drafts


class CancellingComposer(Composer):
    async def compose(self, invocation, **kwargs):
        result = await super().compose(invocation, **kwargs)
        invocation.cancellation.cancel(d.CancellationReason.SUPERSEDED)
        return result


class Conversation:
    def __init__(self):
        self.entries = []

    async def append(self, values) -> None:
        self.entries.extend(values)

    def read(self):
        return SimpleNamespace(summary=SimpleNamespace(text="已有总结"), entries=tuple(self.entries))


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
        composition=Composer(),
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
        assert handler._composition is runtime.skills.response_composition
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_due_reminder_generates_then_persists_and_emits_formal_reply():
    # Given: a non-first-login due fact reaches the real proactive handler.
    composer = Composer(
        (
            ReplyDraft(
                content="今天好像有个特别的日子，你有什么安排吗？",
                sound_content="今天好像有个特别的日子，你有什么安排吗？",
                tone="happy",
                expression="smile",
            ),
        )
    )
    handler = FirstLoginHandler(
        prepared_names=(),
        prepared_speech=PreparedSpeechCatalog({}),
        composition=composer,
    )
    agent = Agent(
        character_id="luotianyi",
        stimulus_router=StimulusRouter(((d.StimulusKind.PROACTIVE_PROMPT_DUE, handler),)),
    )
    sink = PlanSink()
    conversation = Conversation()
    context = SimpleNamespace(
        identity=SimpleNamespace(
            interaction_id="interaction",
            character_id="luotianyi",
            user_id="user",
        ),
        conversation=conversation,
        user=SimpleNamespace(read=lambda: SimpleNamespace()),
    )

    # When: Agent handles the reminder through its public handle entrypoint.
    report = await agent.handle_stimulus(
        first_login_request("holiday"),
        sink,
        context=context,
    )

    # Then: the prompt stays internal; only the generated reply is persisted and realized.
    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert composer.calls[0]["reply_topic"] == "有一项到期提醒（节日），请自然地告诉用户并关心用户的安排。"
    assert composer.calls[0]["conversation_history"] == "已有总结"
    assert composer.calls[0]["invocation"].user_id == "user"
    assert [entry.content.text for entry in conversation.entries] == ["今天好像有个特别的日子，你有什么安排吗？"]
    assert len(sink.values) == 1
    assert len(sink.values[0].actions) == 1
    action = sink.values[0].actions[0]
    assert isinstance(action, d.Say)
    assert action.content == "今天好像有个特别的日子，你有什么安排吗？"
    assert action.sound_content == action.content
    assert action.tone.value == "happy"
    assert action.expression.expression_id == "smile"
    assert action.message_id == conversation.entries[0].entry_id


@pytest.mark.asyncio
async def test_due_reminder_with_no_deliverable_generation_does_not_persist_prompt_or_emit_plan():
    composer = Composer((ReplyDraft(content="", sound_content="", tone="normal", expression=None),))
    handler = FirstLoginHandler(
        prepared_names=(),
        prepared_speech=PreparedSpeechCatalog({}),
        composition=composer,
    )
    agent = Agent(
        character_id="luotianyi",
        stimulus_router=StimulusRouter(((d.StimulusKind.PROACTIVE_PROMPT_DUE, handler),)),
    )
    sink = PlanSink()
    conversation = Conversation()
    context = SimpleNamespace(
        identity=SimpleNamespace(interaction_id="interaction", character_id="luotianyi", user_id="user"),
        conversation=conversation,
        user=SimpleNamespace(read=lambda: SimpleNamespace()),
    )

    report = await agent.handle_stimulus(first_login_request("holiday"), sink, context=context)

    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert report.emitted_plan_ids == ()
    assert conversation.entries == []
    assert sink.values == []


@pytest.mark.asyncio
async def test_cancelled_due_reminder_does_not_persist_or_emit_late_generation():
    composer = CancellingComposer(
        (ReplyDraft(content="过期回复", sound_content="过期回复", tone="normal", expression=None),)
    )
    handler = FirstLoginHandler(
        prepared_names=(),
        prepared_speech=PreparedSpeechCatalog({}),
        composition=composer,
    )
    agent = Agent(
        character_id="luotianyi",
        stimulus_router=StimulusRouter(((d.StimulusKind.PROACTIVE_PROMPT_DUE, handler),)),
    )
    sink = PlanSink()
    conversation = Conversation()
    context = SimpleNamespace(
        identity=SimpleNamespace(interaction_id="interaction", character_id="luotianyi", user_id="user"),
        conversation=conversation,
        user=SimpleNamespace(read=lambda: SimpleNamespace()),
    )

    report = await agent.handle_stimulus(first_login_request("holiday"), sink, context=context)

    assert report.request_status is d.HandlingRequestStatus.CANCELLED
    assert conversation.entries == []
    assert sink.values == []
