"""#411：真实维护失败与清理安全事实分别决定通话准入。"""

import asyncio
from types import SimpleNamespace

import pytest
from support.call_output import output_sink
from support.call_session_repository import InMemoryCallSessionRepository
from support.context_support import database, entry  # noqa: F401
from support.stage_manager import make_stage_manager

import src.domain.agent as d
from src.adapter.websocket.chat import WebSocketAdapter
from src.agent import Agent
from src.agent.context import ContextFactory
from src.agent.handlers.action.call import AnswerCallHandler
from src.agent.handlers.action.cognitive_maintenance import CognitiveMaintenanceActionHandler
from src.agent.handlers.action.router import ActionRouter
from src.agent.handlers.stimulus.call import CallAnswerRequestedHandler
from src.agent.handlers.stimulus.interaction import InteractionEndingHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.processing.plan_emitter import ActionPlanDraft
from src.agent.skills.adapters.memory.facade import AgentMemory
from src.agent.skills.cognitive_maintenance import CognitiveMaintenanceSkill
from src.domain.call import CallEndReason, CallState
from src.domain.stage.lifecycle import StageEndReason, StageShutdownFailed, StageStartAborted
from src.infrastructure.models.llm.interface import LLMContentInspectionError
from src.infrastructure.observability import ObservabilityService, stage_timing
from src.stage import ChatStage
from src.stage.interaction_lease import InteractionSource

from .test_call_handoff import connected, manager, preparing_call
from .test_call_stage import _eventually, _Transport
from .test_chat_stage import RecordingAgent


class _RejectedModel:
    def __init__(self, error_type):
        self.error_type = error_type
        self.calls = 0

    async def generate_response(self, **kwargs):
        self.calls += 1
        raise self.error_type("maintenance model rejected")


class _Models:
    def __init__(self, error_type):
        self.extraction = _RejectedModel(error_type)
        self.profile = SimpleNamespace(generate_response=self.no_update)

    async def no_update(self, **kwargs):
        return "无需更新"

    def register_llm_module(self, name, config):
        return self.extraction if ".extract." in name else self.profile


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, LLMContentInspectionError])
async def test_real_maintenance_failure_keeps_progress_and_error_spans_while_call_rings(
    database, tmp_path, monkeypatch, capture_project_log, caplog, error_type  # noqa: F811
):
    models = _Models(error_type)
    memory = AgentMemory(
        {"memory_writer": {"llm_module": {}}, "user_profile": {"llm_module": {}}},
        models,
        database_manager=SimpleNamespace(conversation_service=database, memory_store=None),
        vector_store=None,
    )
    maintenance = CognitiveMaintenanceSkill({}, llm_service=None, memories={"luotianyi": memory})
    agent = Agent(
        character_id="luotianyi",
        stimulus_router=StimulusRouter(
            (
                (d.StimulusKind.INTERACTION_ENDING, InteractionEndingHandler()),
                (d.StimulusKind.CALL_ANSWER_REQUESTED, CallAnswerRequestedHandler()),
            )
        ),
        action_router=ActionRouter(
            (
                (d.ActionKind.COGNITIVE_MAINTENANCE, CognitiveMaintenanceActionHandler("luotianyi", maintenance)),
                (d.ActionKind.ANSWER_CALL, AnswerCallHandler()),
            )
        ),
    )
    metrics = ObservabilityService({"db_path": str(tmp_path / "metrics.sqlite3")})
    monkeypatch.setattr(stage_timing, "get_observability_service", lambda: metrics)
    repository = InMemoryCallSessionRepository()
    stages = make_stage_manager(
        get_agent=lambda _: agent,
        adapter=WebSocketAdapter(),
        get_context_factory=lambda _: ContextFactory(character_id="luotianyi", database=database),
        call_sessions=repository,
        call_output_sink=output_sink(_Transport()),
    )
    connection, chat = await connected(stages, user="u")
    context = chat.context
    await context.conversation.append((entry(1),))
    capture_project_log("src.agent.facade")
    capture_project_log(chat._logger.name)
    try:
        await stages.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")
        call = await stages.try_to_get_stage(
            stage_type="call", user_id="u", character_id="luotianyi", client_request_id="request-1"
        )
        await call.start()
        result = await chat.terminate(StageEndReason.SWITCH)
        assert call.state is CallState.RINGING
        record = repository.find_by_request("request-1")
        assert record.state is CallState.RINGING and record.end_reason is None
        assert result.finalization_error == "interaction ending maintenance failed"
        assert result.resources_released and result.cleanup_error is None
        with pytest.raises(RuntimeError, match="已经释放"):
            context.conversation.read()
        assert models.extraction.calls == 1
        assert database.get_cognitive_maintenance_progress("u", character_id="luotianyi") is None
        spans = metrics.get_recent_pipeline_spans(trace_id=f"stage:{chat.interaction_id}")
        by_name = {span["span_name"]: span for span in spans}
        assert by_name["agent.cognitive_maintenance"]["status"] == "error"
        assert by_name["stage.termination.maintenance"]["status"] == "error"
        assert by_name["stage.termination.total"]["status"] == "error"
        assert by_name["stage.termination.total"]["metadata"]["resources_released"] is True
        messages = "\n".join(record.getMessage() for record in caplog.records)
        assert "Stage termination maintenance failed" in messages
        assert error_type.__name__ in messages
        # 真实 Agent 接听策略继续使本次通话接通，不仅是创建了一个 PREPARING 对象。
        assert await call.connection_changed(True, 1)
        await _eventually(lambda: repository.find_by_request("request-1").state is CallState.ACTIVE)
        assert call.state is CallState.ACTIVE
    finally:
        await stages.close()
        metrics.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("work_kind", ["handle", "foreground", "threshold"])
async def test_real_agent_cancel_cleanup_failure_does_not_release_handoff(database, work_kind):  # noqa: F811
    entered = asyncio.Event()
    cleanup_attempts = []

    class Handler:
        async def handle(self, request, plans):
            if work_kind != "handle":
                from dataclasses import replace
                from uuid import uuid4

                from .test_chat_stage import plan

                value = plan(request)
                if work_kind == "threshold":
                    value = replace(
                        value,
                        actions=(
                            d.CognitiveMaintenance(
                                action_id=str(uuid4()), reason=d.MaintenanceReason.COMPACTION_THRESHOLD
                            ),
                        ),
                    )
                await plans.emit(
                    ActionPlanDraft(source_stimulus_ids=(request.stimulus.stimulus_id,), actions=value.actions)
                )
                from .test_chat_stage import report

                return report(request, plans=tuple(plans.accepted_ids))
            return await self.realize(None, None, None)

        async def realize(self, action, context, outputs):
            if isinstance(action, d.CognitiveMaintenance) and action.reason is d.MaintenanceReason.INTERACTION_ENDING:
                return d.ActionResult(
                    action_id=action.action_id,
                    status=d.ActionExecutionStatus.COMPLETED,
                    error_code=None,
                    irreversible_effect_committed=False,
                    effect_ref=None,
                )
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                cleanup_attempts.append(True)
                raise OSError("owned handler resource could not close")

    agent = Agent(
        character_id="luotianyi",
        stimulus_router=StimulusRouter(
            (
                (d.StimulusKind.TEXT_MESSAGE, Handler()),
                (d.StimulusKind.INTERACTION_ENDING, InteractionEndingHandler()),
            )
        ),
        action_router=ActionRouter(
            (
                (d.ActionKind.COGNITIVE_MAINTENANCE, Handler()),
                (d.ActionKind.SAY, Handler()),
            )
        ),
    )
    stages = make_stage_manager(
        get_agent=lambda _: agent,
        adapter=WebSocketAdapter(),
        get_context_factory=lambda _: ContextFactory(character_id="luotianyi", database=database),
        call_sessions=InMemoryCallSessionRepository(),
        call_output_sink=output_sink(_Transport()),
    )
    from .test_chat_stage import stimulus

    connection, chat = await connected(stages, user="u")
    assert chat.stimulus_input_sink.submit(stimulus(user_id="u"))
    await asyncio.wait_for(entered.wait(), 1)
    await stages.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")
    call = await stages.try_to_get_stage(
        stage_type="call", user_id="u", character_id="luotianyi", client_request_id="request-1"
    )
    try:
        result = await chat.terminate(StageEndReason.SWITCH)
        assert cleanup_attempts == [True]
        assert not result.resources_released and result.cleanup_error is not None
        assert call.state is not CallState.RINGING
    finally:
        await asyncio.gather(stages.close(), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["handler", "execution", "branch_failure"])
async def test_ending_timeout_cleanup_failure_keeps_real_agent_handoff_owned(database, phase):  # noqa: F811
    entered = asyncio.Event()

    async def fail_on_cancel():
        try:
            entered.set()
            await asyncio.Event().wait()
        finally:
            raise OSError("ending cleanup failed")

    class Ending:
        async def handle(self, request, plans):
            await fail_on_cancel()

    class Model(_Models):
        def __init__(self):
            super().__init__(RuntimeError)
            self.extraction = SimpleNamespace(generate_response=self.generate)

        async def generate(self, **kwargs):
            await fail_on_cancel()

    models = Model()
    if phase == "branch_failure":

        async def fail_summary(**kwargs):
            await entered.wait()
            raise ValueError("summary branch rejected")

        original_register = models.register_llm_module
        models.register_llm_module = lambda name, config: (
            SimpleNamespace(generate_response=fail_summary)
            if name == "conversation_context_summary"
            else original_register(name, config)
        )
    memory = AgentMemory(
        {"memory_writer": {"llm_module": {}}, "user_profile": {"llm_module": {}}},
        models,
        database_manager=SimpleNamespace(conversation_service=database, memory_store=None),
        vector_store=None,
    )
    maintenance_config = (
        {
            "conversation_compaction": {
                "raw_conversation_context_limit": 1,
                "not_zip_conversation_count": 0,
                "llm_module": {},
            }
        }
        if phase == "branch_failure"
        else {}
    )
    maintenance = CognitiveMaintenanceSkill(maintenance_config, llm_service=models, memories={"luotianyi": memory})
    agent = Agent(
        character_id="luotianyi",
        stimulus_router=StimulusRouter(
            ((d.StimulusKind.INTERACTION_ENDING, Ending() if phase == "handler" else InteractionEndingHandler()),)
        ),
        action_router=ActionRouter(
            ((d.ActionKind.COGNITIVE_MAINTENANCE, CognitiveMaintenanceActionHandler("luotianyi", maintenance)),)
        ),
    )
    stages = make_stage_manager(
        get_agent=lambda _: agent,
        adapter=WebSocketAdapter(),
        get_context_factory=lambda _: ContextFactory(character_id="luotianyi", database=database),
        call_sessions=InMemoryCallSessionRepository(),
        call_output_sink=output_sink(_Transport()),
        config={"stage": {"termination_timeout": 1 if phase == "branch_failure" else 0.2}},
    )
    connection, chat = await connected(stages, user="u")
    context = chat.context
    await context.conversation.append((entry(1), entry(2)) if phase == "branch_failure" else (entry(1),))
    await stages.prepare_call_transition(connection, character_id="luotianyi", client_request_id="request-1")
    call = await stages.try_to_get_stage(
        stage_type="call", user_id="u", character_id="luotianyi", client_request_id="request-1"
    )
    try:
        await asyncio.wait_for(entered.wait(), 1)
        result = await chat.terminate(StageEndReason.SWITCH)
        assert result.finalization_error == (
            "interaction ending maintenance failed" if phase == "branch_failure" else "interaction ending timed out"
        )
        assert result.cleanup_error is not None and not result.resources_released
        assert context.conversation.read().entries
        with pytest.raises(RuntimeError, match="initialization failed"):
            await call.start()
        assert stages._lease_registry.current("u", "luotianyi").source is InteractionSource.CALL_TRANSITION
        with pytest.raises(StageShutdownFailed):
            await stages.close()
    finally:
        await asyncio.gather(stages.close(), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["hangup", "shutdown", "setup_timeout"])
async def test_failed_maintenance_after_call_ends_cannot_resurrect_call(ending):
    entered, release = asyncio.Event(), asyncio.Event()

    async def realize(value, context, sink):
        entered.set()
        await release.wait()
        return SimpleNamespace(status=d.ExecutionStatus.FAILED, error_code=d.ExecutionErrorCode.INTERNAL_ERROR)

    stages, repository, _ = manager(
        agent=RecordingAgent(realize=realize),
        config={"call_setup_timeout": 0.05 if ending == "setup_timeout" else 10, "stage": {"termination_timeout": 5}},
    )
    connection, chat = await connected(stages)
    call = await preparing_call(stages, chat, connection)
    closing = None
    try:
        await asyncio.wait_for(entered.wait(), 1)
        if ending == "shutdown":
            closing = asyncio.create_task(stages.close())
            await _eventually(lambda: call.interaction_ended)
            assert not closing.done()
        elif ending == "hangup":
            await call.terminate(StageEndReason.USER_REQUESTED)
        else:
            await _eventually(lambda: call.interaction_ended)
            await call.terminate(StageEndReason.INITIALIZATION_FAILED)
        assert not chat.context.closed
        assert stages._lease_registry.current("user", "luotianyi").source is InteractionSource.CALL_TRANSITION
        release.set()
        await stages.close()
        if closing is not None:
            await closing
        result = await chat.terminate(StageEndReason.SWITCH)
        assert result.finalization_error == "interaction ending maintenance failed" and result.resources_released
        record = repository.find_by_request("request-1")
        assert record.state not in (CallState.RINGING, CallState.ACTIVE)
        assert (
            record.end_reason
            is {
                "hangup": CallEndReason.USER_HANGUP,
                "shutdown": CallEndReason.SYSTEM_FAILURE,
                "setup_timeout": CallEndReason.SETUP_TIMEOUT,
            }[ending]
        )
        assert stages._lease_registry.current("user", "luotianyi") is None
    finally:
        release.set()
        await stages.close()
        if closing is not None:
            await closing


@pytest.mark.asyncio
async def test_maintenance_timeout_waits_cancel_cleanup_before_ringing():
    entered, cancelling, release = (asyncio.Event() for _ in range(3))

    async def realize(value, context, sink):
        try:
            entered.set()
            await asyncio.Event().wait()
        finally:
            cancelling.set()
            await release.wait()

    stages, repository, _ = manager(
        agent=RecordingAgent(realize=realize), config={"stage": {"termination_timeout": 0.01}}
    )
    connection, chat = await connected(stages)
    call = await preparing_call(stages, chat, connection)
    try:
        await asyncio.wait_for(entered.wait(), 1)
        await asyncio.wait_for(cancelling.wait(), 1)
        assert call.state is CallState.PREPARING and not chat.context.closed
        assert stages._lease_registry.current("user", "luotianyi").source is InteractionSource.CALL_TRANSITION
        release.set()
        await call.start()
        result = await chat.terminate(StageEndReason.SWITCH)
        assert result.finalization_error == "interaction ending timed out" and result.resources_released
        assert repository.find_by_request("request-1").state is CallState.RINGING
    finally:
        release.set()
        await stages.close()


@pytest.mark.asyncio
async def test_context_close_failure_after_maintenance_failure_keeps_transition_owned():
    async def failed_realize(*args):
        return SimpleNamespace(status=d.ExecutionStatus.FAILED, error_code=d.ExecutionErrorCode.INTERNAL_ERROR)

    stages, repository, _ = manager(agent=RecordingAgent(realize=failed_realize))
    connection, chat = await connected(stages)

    async def failed_close():
        raise OSError("context still owned")

    chat.context.close = failed_close
    call = await preparing_call(stages, chat, connection)
    try:
        with pytest.raises(RuntimeError, match="initialization failed"):
            await call.start()
        await call.terminate(StageEndReason.INITIALIZATION_FAILED)
        result = await chat.terminate(StageEndReason.SWITCH)
        assert result.finalization_error == "interaction ending maintenance failed"
        assert result.cleanup_error == "OSError" and not result.resources_released
        assert not chat.context.closed and chat.lifecycle_state.value == "terminating"
        assert stages._lease_registry.current("user", "luotianyi").source is InteractionSource.CALL_TRANSITION
        assert repository.find_by_request("request-1").end_reason is CallEndReason.SYSTEM_FAILURE
        with pytest.raises(RuntimeError, match="USER_INTERACTION_BUSY"):
            await stages.begin_user_data_reset("user")
        with pytest.raises(StageShutdownFailed):
            await stages.close()
    finally:
        await asyncio.gather(stages.close(), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_failure", [False, True])
async def test_active_chat_initialization_cancel_distinguishes_cleanup_error(cleanup_failure):
    entered, release, cancelling = (asyncio.Event() for _ in range(3))

    class Factory:
        async def create(self, *args, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError as error:
                cancelling.set()
                await release.wait()
                if cleanup_failure:
                    raise OSError("initialization cleanup failed") from error
                raise

    stage = await ChatStage.create(
        user_id="user",
        character_id="luotianyi",
        agent=RecordingAgent(),
        context_factory=Factory(),
        output_sink=WebSocketAdapter().output_sink,
    )
    await asyncio.wait_for(entered.wait(), 1)
    stopping = asyncio.create_task(stage.terminate(StageEndReason.SHUTDOWN))
    try:
        await asyncio.wait_for(cancelling.wait(), 1)
        assert not stopping.done() and stage.lifecycle_state.value == "terminating"
        release.set()
        result = await asyncio.wait_for(stopping, 1)
        assert result.resources_released is not cleanup_failure
        assert (result.cleanup_error is not None) is cleanup_failure
        assert stage.lifecycle_state.value == ("terminating" if cleanup_failure else "terminated")
        assert await stage.terminate(StageEndReason.SHUTDOWN) is result
        with pytest.raises(StageStartAborted):
            await stage.start()
    finally:
        release.set()
        await stopping
