from contextlib import closing

import pytest
from support import call_omni
from support.call_omni import _eventually, _SayHandler, create_stage, send_reply
from support.stage_lifecycle import finish_call

from src.infrastructure.observability import reply_metrics
from src.infrastructure.observability.call_metrics import CallMetrics
from src.infrastructure.observability.call_reply_timing import mark_reply_phase
from src.infrastructure.observability.service import ObservabilityService

call_setup = call_omni.call_setup


@pytest.mark.asyncio
async def test_call_latency_panel_counts_ack_and_unacknowledged_turns(call_setup, tmp_path, monkeypatch):
    clock = call_setup[-1]
    realize = _SayHandler.realize

    async def synthesize(handler, action, context, outputs):
        clock.advance(0.2)
        mark_reply_phase("tts_synthesized")
        return await realize(handler, action, context, outputs)

    monkeypatch.setattr(_SayHandler, "realize", synthesize)
    with closing(ObservabilityService({"db_path": str(tmp_path / "metrics.sqlite3")})) as metrics:
        monkeypatch.setattr(reply_metrics, "get_observability_service", lambda: metrics)
        stage, socket, transport, _ = await create_stage(call_setup)
        stage._call_metrics = CallMetrics(metrics)

        def call_panel():
            return next(group for group in metrics.latency_groups("all")["groups"] if group["id"] == "call")

        try:
            payload = b"\x00\x01"
            assert stage.accept_pcm(call_omni._receipt(stage.call_id, 1, payload), payload)
            assert stage.accept_pcm(call_omni._receipt(stage.call_id, 2, payload), payload)
            await send_reply(socket, text="回复。")
            response_id = "r1-segment-0"
            await _eventually(
                lambda: any(item[:2] == ("pcm", response_id) for item in transport.items if isinstance(item, tuple))
            )
            assert call_panel()["outcomes"] == {"pending": 1}
            clock.advance(0.3)
            stage.audio_acknowledged(response_id)
            stage.audio_acknowledged(response_id)
            assert call_panel()["outcomes"] == {"success": 1}

            await socket.server_event({"type": "input_audio_buffer.speech_started", "item_id": "u2"})
            await socket.server_event({"type": "input_audio_buffer.speech_stopped", "item_id": "u2"})
            await _eventually(lambda: call_panel()["outcomes"] == {"success": 1, "pending": 1})
        finally:
            await finish_call(stage)

        panel = call_panel()
        recorded = metrics.get_recent_pipeline_spans(trace_id=f"call:{stage.call_id}")
        assert any(row["span_name"] == "call.interrupt" for row in recorded)
        assert all(row["span_name"] != "call.buffer" for row in recorded)
        assert panel["outcomes"] == {"success": 1, "incomplete": 1}
        rows = {row["key"]: row for row in panel["rows"]}
        for phase, expected_ms in (("ack", 500), ("tts", 200), ("tts_to_ack", 300)):
            assert rows[phase]["count"] == 1
            assert rows[phase]["avg_ms"] == pytest.approx(expected_ms)
