"""登录与周期提醒的筛选、claim、空闲和释放契约。"""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import src.domain.agent as d
from src.adapter.websocket import WebSocketAdapter
from src.stage import DueEvent, StageManager
from src.system.user_interface.websocket_service import WebSocketConnection


class Socket:
    async def send_json(self, event: dict) -> None:
        return None


class ContextFactory:
    async def create(self, interaction_id: str, *, user_id: str):
        return SimpleNamespace(
            identity=SimpleNamespace(
                interaction_id=interaction_id,
                user_id=user_id,
                character_id="luotianyi",
            ),
            recalled_memory=SimpleNamespace(remove_by_stimulus_id=lambda _: None),
            close=self._close,
        )

    async def _close(self) -> None:
        return None


class DueEvents:
    def __init__(self, events: tuple[DueEvent, ...]) -> None:
        self.events = events
        self.claimed: set[tuple[str, str, str, str]] = set()
        self.claim_calls: list[str] = []
        self.released: list[str] = []

    def list_due(self, *, character_id: str, user_id: str, now: datetime) -> tuple[DueEvent, ...]:
        return self.events

    def claim(
        self,
        event_id: str,
        *,
        user_id: str,
        character_id: str,
        trigger_key: str,
    ) -> bool:
        self.claim_calls.append(event_id)
        key = (event_id, user_id, character_id, trigger_key)
        if key in self.claimed:
            return False
        self.claimed.add(key)
        return True

    def release(
        self,
        event_id: str,
        *,
        user_id: str,
        character_id: str,
        trigger_key: str,
    ) -> None:
        self.claimed.discard((event_id, user_id, character_id, trigger_key))
        self.released.append(event_id)


def event(
    event_id: str,
    *,
    event_type: str = "holiday",
    character_id: str = "luotianyi",
    is_personal: bool = False,
    target_user_id: str | None = None,
    is_notified: bool = False,
) -> DueEvent:
    return DueEvent(
        event_id=event_id,
        trigger_key="day_of_event",
        reason=event_type,
        due_at=datetime.now(timezone.utc),
        character_id=character_id,
        is_personal=is_personal,
        target_user_id=target_user_id,
        is_notified=is_notified,
    )


def completed_report(request: d.HandleStimulusRequest, plan_ids: tuple[str, ...] = ()) -> d.HandlingReport:
    return d.HandlingReport(
        request_id=request.request_id,
        trigger_stimulus_id=request.stimulus.stimulus_id,
        basis_interaction_revision=request.interaction.interaction_revision,
        request_status=d.HandlingRequestStatus.COMPLETED,
        considered_pending_stimulus_ids=(),
        consumed_pending_stimulus_ids=(),
        retained_pending_stimulus_ids=(),
        emitted_plan_ids=plan_ids,
        retryable=False,
        error_code=None,
    )


class RecordingAgent:
    def __init__(self, *, fail_handle: bool = False) -> None:
        self.fail_handle = fail_handle
        self.stimuli: list[d.ProactivePromptDue] = []

    async def handle_stimulus(self, request, sink, *, context=None):
        if isinstance(request.stimulus, d.ProactivePromptDue):
            self.stimuli.append(request.stimulus)
            if self.fail_handle:
                return d.HandlingReport(
                    request_id=request.request_id,
                    trigger_stimulus_id=request.stimulus.stimulus_id,
                    basis_interaction_revision=request.interaction.interaction_revision,
                    request_status=d.HandlingRequestStatus.FAILED,
                    considered_pending_stimulus_ids=(),
                    consumed_pending_stimulus_ids=(),
                    retained_pending_stimulus_ids=(),
                    emitted_plan_ids=(),
                    retryable=False,
                    error_code=d.HandlingErrorCode.INTERNAL_ERROR,
                )
            action = d.Say(
                action_id=f"say:{request.stimulus.stimulus_id}",
                content="reminder",
                sound_content=None,
                prepared_audio_ref=None,
                tone=d.Tone(value="normal"),
                expression=d.ChangeExpression(expression_id="normal"),
                delivery=d.OutputDelivery.CONVERSATION,
            )
            plan = d.ActionPlan(
                plan_id=f"plan:{request.request_id}",
                origin_request_id=request.request_id,
                plan_ordinal=0,
                target_character_id="luotianyi",
                interaction_id=request.interaction.interaction_id,
                basis_interaction_revision=request.interaction.interaction_revision,
                source_stimulus_ids=(request.stimulus.stimulus_id,),
                actions=(action,),
            )
            await sink.emit(plan)
            return completed_report(request, (plan.plan_id,))
        return completed_report(request)

    async def realize_action_plan(self, plan, context, sink):
        action = plan.actions[0]
        return d.ExecutionReport(
            execution_id=context.execution_id,
            plan_id=plan.plan_id,
            status=d.ExecutionStatus.COMPLETED,
            action_results=(d.ActionResult(
                action_id=action.action_id,
                status=d.ActionExecutionStatus.COMPLETED,
                error_code=None,
                irreversible_effect_committed=False,
                effect_ref=None,
            ),),
            output_started=False,
            error_code=None,
            retryable=False,
        )


async def connected_manager(provider: DueEvents, agent: RecordingAgent, **stage_config):
    manager = StageManager(
        get_agent=lambda _: agent,
        adapter=WebSocketAdapter(),
        get_context_factory=lambda _: ContextFactory(),
        due_event_provider=provider,
        config={"stage": {"proactive_idle_seconds": 0.01, **stage_config}},
    )
    stage = await manager.connect(
        WebSocketConnection(Socket(), "user", "用户"),
        "luotianyi",
    )
    return manager, stage


async def wait_until(predicate, timeout: float = 1.0) -> None:
    async def wait() -> None:
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(wait(), timeout)


@pytest.mark.asyncio
async def test_regular_login_filters_before_claim_and_merges_supported_due_events():
    # Given: a first login today has supported, unsupported, mismatched and notified candidates.
    provider = DueEvents((
        event("holiday"),
        event("birthday", event_type="birthday", is_personal=True, target_user_id="user"),
        event("unsupported", event_type="general"),
        event("other-character", character_id="miku"),
        event("other-user", is_personal=True, target_user_id="other"),
        event("notified", is_notified=True),
    ))
    agent = RecordingAgent()
    manager, _stage = await connected_manager(provider, agent, login_reminder_wait=0.01)

    # When: the manager records the day's first ordinary login.
    manager.record_login("user", "luotianyi", elapsed_from_last_login=24 * 60 * 60)
    await wait_until(lambda: len(agent.stimuli) == 1)

    # Then: only supported stream-owned facts are claimed and merged into one Agent stimulus.
    assert provider.claim_calls == ["holiday", "birthday"]
    assert len(agent.stimuli) == 1
    assert {ref.evidence_id for ref in agent.stimuli[0].fact_refs} == {"holiday", "birthday"}
    await manager.close()


@pytest.mark.asyncio
async def test_periodic_scan_waits_for_idle_and_selects_one_candidate_per_stream(monkeypatch):
    # Given: an online Stage with two eligible reminders and a configured idle threshold.
    provider = DueEvents((event("first"), event("second")))
    agent = RecordingAgent()
    manager, stage = await connected_manager(provider, agent, proactive_idle_seconds=0.03)
    monkeypatch.setattr("src.stage.chat_stage.random.choice", lambda values: values[-1])

    # When: scans run before and after the Stage reaches the effective idle threshold.
    assert await manager.scan_due_events() == 0
    await asyncio.sleep(0.035)
    assert await manager.scan_due_events() == 1
    await asyncio.sleep(0.01)

    # Then: exactly the selected candidate is claimed and dispatched.
    assert provider.claim_calls == ["second"]
    assert [ref.evidence_id for ref in agent.stimuli[0].fact_refs] == ["second"]
    assert stage.state.name == "ONLINE"
    await manager.close()


@pytest.mark.asyncio
async def test_busy_stage_does_not_claim_or_preempt_user_reply():
    # Given: a Stage whose user input is still being handled.
    gate = asyncio.Event()
    provider = DueEvents((event("due"),))

    class BusyAgent(RecordingAgent):
        async def handle_stimulus(self, request, sink, *, context=None):
            if isinstance(request.stimulus, d.UserTyping):
                await gate.wait()
                return completed_report(request)
            return await super().handle_stimulus(request, sink, context=context)

    manager, stage = await connected_manager(provider, BusyAgent(), proactive_idle_seconds=0.01)
    typing = d.UserTyping(
        stimulus_id="typing",
        schema_version=1,
        occurred_at=datetime.now(timezone.utc),
        source=d.StimulusSource.USER,
        target_character_ids=("luotianyi",),
        user_id="user",
        ephemeral=True,
        text_length=1,
    )
    assert stage.stimulus_input_sink.submit(typing)
    await asyncio.sleep(0.02)

    # When: the periodic wake occurs while the ordinary handle is busy.
    assert await manager.scan_due_events() == 0

    # Then: no reminder claim is taken; releasing the user handle permits a later scan.
    assert provider.claim_calls == []
    gate.set()
    await asyncio.sleep(0.02)
    assert await manager.scan_due_events() == 1
    await manager.close()


@pytest.mark.asyncio
async def test_failed_dispatch_releases_claim_for_login_periodic_retry():
    # Given: the login path claims a reminder but Agent handling fails.
    provider = DueEvents((event("shared"),))
    failing = RecordingAgent(fail_handle=True)
    manager, _stage = await connected_manager(provider, failing, login_reminder_wait=0.01)
    manager.record_login("user", "luotianyi", elapsed_from_last_login=24 * 60 * 60)
    await wait_until(lambda: provider.released == ["shared"])

    # When: a later periodic scan retries the same identity with a healthy Agent.
    assert provider.released == ["shared"]
    manager._get_agent = lambda _: RecordingAgent()
    manager._stages[("user", "luotianyi")]._agent = manager._get_agent("luotianyi")
    manager._stages[("user", "luotianyi")]._last_activity_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert await manager.scan_due_events() == 1

    # Then: the shared claim identity can be reacquired after failure.
    assert provider.claim_calls == ["shared", "shared"]
    await manager.close()


@pytest.mark.asyncio
async def test_successful_login_claim_blocks_periodic_duplicate():
    # Given: the ordinary-login path successfully claims and realizes one reminder.
    provider = DueEvents((event("shared"),))
    manager, stage = await connected_manager(provider, RecordingAgent(), login_reminder_wait=0.01)
    manager.record_login("user", "luotianyi", elapsed_from_last_login=24 * 60 * 60)
    await wait_until(lambda: len(provider.claimed) == 1 and not stage._proactive_claims)
    stage._last_activity_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    # When: the periodic path sees the same event/user/character/trigger identity.
    assert await manager.scan_due_events() == 0

    # Then: the durable successful claim prevents a duplicate dispatch.
    assert provider.claim_calls == ["shared", "shared"]
    assert provider.released == []
    await manager.close()
