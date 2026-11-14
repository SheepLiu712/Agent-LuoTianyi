import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.infrastructure.observability import ObservabilityService, get_observability_service, set_observability_service
from src.infrastructure.observability import population, tts_metrics
from src.infrastructure.observability.population import PopulationSampler
from src.infrastructure.observability.tts_metrics import TTSRequest, worker_event
from src.stage.stage_manager import StageManager, _StageRegistration
from src.stage.chat.chat_stage import ChatStage
from src.stage.call.call_stage import CallStage
from src.domain.stage.lifecycle import StageLifecycleState


@pytest.fixture
def metrics(tmp_path):
    store = ObservabilityService({"db_path": str(tmp_path / "metrics.db")})
    previous = get_observability_service()
    set_observability_service(store)
    yield store
    set_observability_service(previous)
    with tts_metrics._lock:
        tts_metrics._requests.clear()
    store.close()


def counts(value):
    return dict(
        scope_count=value, chat_stage_count=value, call_stage_count=0, overlap_count=0, terminating_stage_count=0
    )


def span(store, identity, name, duration, at, status="success", **metadata):
    store.record_pipeline_span(
        trace_id=identity,
        span_name=name,
        start_ts=at.isoformat(),
        end_ts=at.isoformat(),
        duration_ms=duration,
        status=status,
        metadata=metadata,
    )


def test_usage_continuous_buckets_distinguish_missing_and_zero(metrics):
    now = datetime(2026, 11, 15, 0, 10, tzinfo=timezone.utc)
    metrics.record_population((now - timedelta(minutes=10)).isoformat(), "run", counts(8))
    metrics.record_population(now.isoformat(), "run", counts(0))
    for at, tokens in [(now - timedelta(minutes=10), 100), (now, 200)]:
        metrics._execute(
            "INSERT INTO llm_call_metrics(ts,module_name,total_tokens) VALUES (?,?,?)",
            (at.isoformat(), "reply", tokens),
        )
    daily = metrics.usage_trends(now=now)
    assert len(daily["rows"]) == 289
    assert [r["online"] for r in daily["rows"][-3:]] == [8, None, 0]
    assert [r["calls"] for r in daily["rows"][-3:]] == [1, 0, 1]
    assert daily["totals"] == {"calls": 2, "tokens": 300, "online_peak": 8}
    weekly = metrics.usage_trends("7d", now=now)
    assert weekly["rows"][-1]["online"] == 4
    assert weekly["rows"][-1]["online_peak"] == 8
    assert weekly["rows"][-1]["tokens"] == 300
    assert daily["timezone"] == "Asia/Shanghai"


def test_windows_stage_grouping_and_legacy_exclusion(metrics):
    now = datetime.now(timezone.utc)
    for key, days, value in [("old", 9, 100), ("week", 2, 200), ("new", 0, 300)]:
        span(metrics, key, "chat.v2.generation", value, now - timedelta(days=days, seconds=1))
    span(metrics, "legacy", "call.reply.generation", 999999, now - timedelta(seconds=1))
    for value in (20, 30):
        span(metrics, "stage-one", "stage.termination.stop_tasks", value, now, stage_kind="call")
    span(metrics, "stage-two", "stage.termination.stop_tasks", 500, now, "error", stage_kind="call")

    def group(window, name):
        return next(g for g in metrics.latency_groups(window, now=now)["groups"] if g["id"] == name)

    for window, count, avg in [("24h", 1, 300), ("7d", 2, 250), ("all", 3, 200)]:
        row = next(r for r in group(window, "chat")["rows"] if r["key"] == "generation")
        assert row["count"] == count and row["avg_ms"] == avg
    assert all(row["count"] == 0 for row in group("all", "call")["rows"])
    row = next(r for r in group("all", "stage_call")["rows"] if r["key"] == "stop_tasks")
    assert row["count"] == 1 and row["p99_ms"] == 50


def test_population_deduplicates_user_character_and_counts_retained_stages():
    class Chat(ChatStage):
        @property
        def lifecycle_state(self):
            return StageLifecycleState.TERMINATING

    class Call(CallStage):
        @property
        def character_id(self):
            return self.character

        @property
        def lifecycle_state(self):
            return StageLifecycleState.RUNNING

    manager = object.__new__(StageManager)
    chat = object.__new__(Chat)
    chat._character_id = "tianyi"
    call, second = object.__new__(Call), object.__new__(Call)
    call.character, second.character = "tianyi", "yanhe"
    manager._managed = {
        str(i): _StageRegistration(stage, "same-user", lambda: None) for i, stage in enumerate((chat, call, second))
    }
    assert manager.snapshot_population() == dict(
        scope_count=2, chat_stage_count=1, call_stage_count=2, overlap_count=1, terminating_stage_count=1
    )


@pytest.mark.asyncio
async def test_sampler_five_minute_alignment(metrics, monkeypatch):
    clock, delays = [299.0], []

    async def sleep(delay):
        delays.append(delay)
        if len(delays) > 1:
            raise asyncio.CancelledError
        clock[0] += delay

    monkeypatch.setattr(population, "time", SimpleNamespace(time=lambda: clock[0]))
    sampler = PopulationSampler(SimpleNamespace(snapshot_population=lambda: counts(2)), metrics)
    monkeypatch.setattr(population, "asyncio", SimpleNamespace(sleep=sleep, to_thread=asyncio.to_thread))
    with pytest.raises(asyncio.CancelledError):
        await sampler._run()
    assert delays == [1, 300]
    assert len(metrics._query_all("SELECT * FROM stage_population_samples")) == 1


def test_cancelled_tts_keeps_worker_occupancy_until_actual_finish(metrics):
    invocation = SimpleNamespace(user_id="user", character_id="tianyi", interaction_id="session")
    first, second = TTSRequest(invocation), TTSRequest(invocation)
    first.mark("bound", worker="shared")
    second.mark("bound", worker="shared")
    origin = first.marks["requested"]
    first.mark("submitted")
    worker_event(first.id, "worker_started", int((origin + 1) * 1e9))
    first.finish("cancelled")
    assert first.id in tts_metrics._requests
    worker_event(first.id, "first_audio", int((origin + 2) * 1e9))
    row = metrics._query_all("SELECT * FROM tts_requests WHERE request_id=?", (first.id,))[0]
    assert row["status"] == "cancelled"
    assert row["queue_ms"] == pytest.approx(1000, abs=0.01)
    assert row["first_audio_ms"] == pytest.approx(2000, abs=0.01)
    assert row["returned_ms"] is None
    worker_event(first.id, "worker_finished", int((origin + 3) * 1e9))
    assert first.id not in tts_metrics._requests
    second.finish("cancelled")
    assert second.id not in tts_metrics._requests
    windows = metrics._query_all("SELECT * FROM tts_queue_windows")
    assert max(r["waiting_peak"] for r in windows) == 2
    assert max(r["running_peak"] for r in windows) == 1
    group = next(g for g in metrics.latency_groups()["groups"] if g["id"] == "tts")
    assert group["outcomes"] == {"cancelled": 2}
    assert group["rows"][0]["count"] == 1


def test_reopen_and_retention_preserve_then_expire_new_records(tmp_path):
    path = str(tmp_path / "metrics.db")
    store = ObservabilityService({"db_path": path, "retention_days": 1})
    store.record_population("2000-01-01T00:00:00+00:00", "old", counts(1))
    store.close()
    store = ObservabilityService({"db_path": path, "retention_days": 1})
    try:
        assert len(store._query_all("SELECT * FROM stage_population_samples")) == 1
        store.cleanup_old_records()
        assert store._query_all("SELECT * FROM stage_population_samples") == []
    finally:
        store.close()


def test_metrics_api_auth_and_shared_window_validation(metrics, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.application.admin.auth import AdminAuthError
    from src.web.admin import admin_interface

    class Auth:
        def require_admin(self, token):
            if token != "allowed":
                raise AdminAuthError(401, {"code": "AUTH_REQUIRED", "message": "需要登录"})

    monkeypatch.setattr(admin_interface, "get_admin_shell", lambda: SimpleNamespace(auth=Auth(), observability=metrics))
    app = FastAPI()
    app.include_router(admin_interface.protected_router, prefix="/admin/api")
    with TestClient(app) as client:
        for path in ("usage", "latency"):
            assert client.get(f"/admin/api/metrics/{path}").status_code == 401
            response = client.get(f"/admin/api/metrics/{path}", headers={"Authorization": "Bearer allowed"})
            assert response.status_code == 200 and response.json()["window"] == "24h"
        for window in ("24h", "7d", "all"):
            assert (
                client.get(
                    f"/admin/api/metrics/latency?window={window}", headers={"Authorization": "Bearer allowed"}
                ).status_code
                == 200
            )
        assert (
            client.get("/admin/api/metrics/latency?window=bad", headers={"Authorization": "Bearer allowed"}).status_code
            == 422
        )


@pytest.mark.asyncio
async def test_sampler_start_stop_does_not_duplicate_background_tasks(metrics):
    sampler = PopulationSampler(SimpleNamespace(snapshot_population=lambda: counts(0)), metrics)
    sampler.start()
    task = sampler.task
    sampler.start()
    assert task is sampler.task
    await sampler.stop()
    await sampler.stop()
    assert task.done() and sampler.task is None


@pytest.mark.asyncio
async def test_real_tts_stream_lock_wait_and_worker_metrics(metrics, tmp_path):
    import queue
    import threading
    import time
    from contextlib import aclosing
    from src.agent.skills.expression.speaking.skill import SpeakingSkill
    from src.agent.skills.expression.speaking.streaming import AsyncTTS
    from src.agent.skills.expression.speaking.tts_server import TTSServer
    from src.agent.skills.contracts import SkillInvocation
    from src.domain.agent import CancellationToken, Tone

    server = TTSServer(str(tmp_path / "unused.yaml"))
    server.server_process = SimpleNamespace(is_alive=lambda: True)
    server.request_queue, server.response_queue = queue.Queue(), queue.Queue()
    entered, release = threading.Event(), threading.Event()

    def worker():
        message = server.request_queue.get(timeout=3)
        worker_event(message["telemetry_id"], "worker_started", time.monotonic_ns())
        entered.set()
        release.wait(3)
        worker_event(message["telemetry_id"], "first_audio", time.monotonic_ns())
        server.response_queue.put({"request_id": message["request_id"], "ok": True, "audio_bytes": b"audio"})
        worker_event(message["telemetry_id"], "worker_finished", time.monotonic_ns())
        server.response_queue.put({"request_id": message["request_id"], "ok": True, "is_final": True})

    thread = threading.Thread(target=worker)
    thread.start()

    class Module:
        tts_server = server

        def stream_synthesize_speech_with_tone(self, text, tone, cancel_event):
            return server.stream_synthesize(text, "ref", "ref", "prompt", cancel_event=cancel_event)

    skill = SpeakingSkill({}, tts_engine=AsyncTTS(SimpleNamespace(tts_module={"tianyi": Module()})))
    first_token, second_token = CancellationToken(), CancellationToken()

    async def speak(user, token):
        invocation = SkillInvocation("tianyi", user, "interaction", token)
        async with aclosing(skill.speak(invocation, text="正文不应落库", tone=Tone(value="normal"))) as stream:
            return [chunk.data async for chunk in stream]

    first = asyncio.create_task(speak("first", first_token))
    second = None
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        second = asyncio.create_task(speak("second", second_token))

        async def wait_registered():
            while len(metrics._query_all("SELECT * FROM tts_requests")) < 2:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_registered(), 2)
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        release.set()
        assert await asyncio.wait_for(first, 2) == [b"audio"]
        rows = {r["user_id"]: r for r in metrics._query_all("SELECT * FROM tts_requests")}
        assert rows["first"]["status"] == "success"
        assert rows["first"]["returned_ms"] >= rows["first"]["first_audio_ms"] >= rows["first"]["queue_ms"]
        assert rows["second"]["status"] == "cancelled" and rows["second"]["first_audio_ms"] is None
        assert "正文不应落库" not in str(rows)
    finally:
        release.set()
        if second is not None and not second.done():
            second.cancel()
        await asyncio.gather(first, *([second] if second is not None else []), return_exceptions=True)
        await asyncio.to_thread(thread.join, 3)


def test_call_v2_worker_first_audio_uses_submission_not_parent_delivery():
    from src.infrastructure.observability.call_reply_timing import CallReplyTiming

    clock, result = [1.0], []
    timing = CallReplyTiming(
        call_id="call",
        request_id="reply",
        turn_seq=1,
        recognized_at=0,
        speech_ended_at=0,
        sink=None,
        clock=lambda: clock[0],
        v2_sink=lambda *values: result.append(values),
    )
    timing.mark("reply_submitted")
    clock[0] = 9
    timing.mark("tts_started", at=2)
    timing.mark("tts_synthesized", at=3)
    timing.mark("tts_first_packet")
    assert result == [("tts", 1.0, 3)]


@pytest.mark.asyncio
async def test_chat_model_first_draft_and_output_acceptance_have_distinct_boundaries(metrics, monkeypatch):
    from dataclasses import dataclass
    import src.domain.agent as d
    from src.agent.context import UserContextSnapshot
    from src.agent.skills.cognitive.reply import ReplySkill
    from src.agent.skills.contracts import ReplyDraft
    from src.infrastructure.observability import reply_metrics
    from src.stage.chat._sinks import _AgentOutputSink

    clock = [10.0]
    monkeypatch.setattr(reply_metrics, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    timing = reply_metrics.ChatReplyTiming("request", 5)

    @dataclass
    class Prompt:
        pass

    class Model:
        stream = True

        async def generate_response(self, on_delta, **kwargs):
            clock[0] = 20
            await on_delta("[中性]这是一段足够长的测试回复。")

    resource = SimpleNamespace(
        character_name="天依",
        character_persona="",
        speaking_style="",
        prompt_assembler=SimpleNamespace(build=lambda **kwargs: Prompt()),
        _build_preference_context=lambda user: "",
        llm=Model(),
        response_parser=SimpleNamespace(
            _parse_tone_line=lambda tone, text: ReplyDraft(
                content=text, sound_content=text, tone="normal", expression=None
            )
        ),
    )
    skill = object.__new__(ReplySkill)
    skill._resources = {"tianyi": resource}
    with reply_metrics.chat_reply_scope(timing):
        drafts = [
            draft async for draft in skill.generate("tianyi", reply_topic="话题", user_context=UserContextSnapshot())
        ]
    assert len(drafts) == 1
    clock[0] = 30
    stage = SimpleNamespace(
        interaction_id="interaction",
        _execution=SimpleNamespace(execution_id="execution", cancellation=d.CancellationToken()),
        _executing_plan=SimpleNamespace(origin_request_id="request"),
        _attempts={"request": SimpleNamespace(timing=timing)},
        _send=lambda output: None,
    )
    output = d.TextFinalOutput(
        interaction_id="interaction",
        execution_id="execution",
        action_id="action",
        sequence_no=0,
        delivery=d.OutputDelivery.CONVERSATION,
        text=drafts[0].content,
    )
    sink = _AgentOutputSink(stage)
    await sink.emit(output)
    await sink.emit(output)
    rows = {r["span_name"]: r for r in metrics._query_all("SELECT * FROM pipeline_spans")}
    assert rows["chat.v2.generation"]["duration_ms"] == 10000
    assert rows["chat.v2.delivery"]["duration_ms"] == 10000
    assert rows["chat.v2.total"]["duration_ms"] == 25000
    assert len(metrics._query_all("SELECT * FROM pipeline_spans WHERE span_name='chat.v2.total'")) == 1


def test_background_metric_failure_does_not_break_request_or_close(metrics):
    def fail():
        raise RuntimeError("unavailable")

    metrics.defer_metric_write(fail)
    metrics.defer_metric_write(metrics.record_population, datetime.now(timezone.utc).isoformat(), "run", counts(1))
    assert len(metrics._query_all("SELECT * FROM stage_population_samples")) == 1
