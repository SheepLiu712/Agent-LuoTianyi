"""确认分析脚本不把 ACK 冒充播放，且缺失反馈不统计为零。"""

import json

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_spec = spec_from_file_location(
    "call_latency_analysis", Path(__file__).resolve().parents[3] / "scripts/analyze_call_latency.py"
)
_module = module_from_spec(_spec)
_spec.loader.exec_module(_module)
analyze, read_events = _module.analyze, _module.read_events


def test_parse_log_and_measure_hold_ack_replay_and_missing_feedback(tmp_path):
    def event(name, ms, **fields):
        return {
            "schema": 1,
            "process_run": "run",
            "call_id": "call",
            "response_id": "reply",
            "event": name,
            "monotonic_ns": ms * 1_000_000,
            **fields,
        }

    events = [
        event("reply.response", 1, turn_seq=1),
        event("audio.generated", 100, packet_index=0, provisional=False),
        event("audio.hold_released", 160, packet_index=0),
        event("audio.enqueued", 170, seq=2),
        event("audio.sent", 180, seq=2),
        event("audio.sent", 200, seq=2),
        event("audio.ack", 250, seq=2),
        event("audio.generated", 270, packet_index=1),
    ]
    path = tmp_path / "server.log"
    path.write_text(
        "ordinary log\n" + "\n".join("INFO CALL_LATENCY " + json.dumps(e) for e in events * 2), encoding="utf-8"
    )
    result = analyze(read_events([path]))
    row = result["responses"][0]
    assert row["first_packet_hold_ms"] == 60
    assert row["first_packet_to_ack_ms"] == 150
    assert row["wire_packets"][0]["sent_to_ack_ms"] == 70
    assert row["wire_packets"][0]["send_attempts"] == 2
    assert row["first_packet_to_stream_completed_ms"] is None
    assert row["generated_packets"][1]["hold_ms"] is None
    assert "不代表播放" in result["measurement"]


def test_realtime_measurements_keep_model_segment_and_provider_stop_without_final_transcript():
    def event(name, ms, **fields):
        return dict(event=name, monotonic_ns=ms * 1_000_000, call_id="call", **{"process_run": "run", **fields})

    result = analyze(
        [
            event("input.provider_speech_stopped", 10, turn_seq=1, item_id="input"),
            event("reply.generation_started", 20, response_id="model"),
            event("reply.response", 30, response_id="segment", model_response_id="model", segment_index=0, turn_seq=1),
            event("audio.generated", 40, response_id="segment"),
            event("audio.ack", 70, response_id="segment"),
        ]
    )
    assert len(result["responses"]) == 1
    row = result["responses"][0]
    assert row["speech_end_basis"] == "provider_speech_stopped_received"
    assert row["model_response_id"] == "model" and row["segment_index"] == 0
    assert result["turns"][0]["first_response_id"] is None
    assert result["turns"][0]["first_ack_response_id"] == "segment"
    assert row["speech_end_to_first_ack_ms"] == 60
    assert row["first_packet_to_stream_completed_ms"] is None


def test_turn_totals_select_valid_retry_once_and_keep_missing_ack():
    def e(name, ms, response_id=None, **fields):
        return dict(
            event=name,
            monotonic_ns=ms * 1_000_000,
            process_run="run",
            call_id="call",
            response_id=response_id,
            **fields,
        )

    events = [e("input.provider_speech_stopped", 10, turn_seq=1), e("input.provider_speech_stopped", 500, turn_seq=2)]
    for response, start, index in (("failed", 20, 0), ("retry", 100, 0), ("later", 300, 1), ("proactive", 400, 0)):
        events += [
            e(
                "reply.response",
                start,
                response,
                turn_seq=None if response == "proactive" else 1,
                model_response_id="model",
                segment_index=index,
            ),
            e("tts.requested", start + 10, response),
            e("tts.started", start + 30, response),
            e("tts.synthesized", start + 70, response),
            e("audio.generated", start + 75, response),
            e("audio.sent", start + 80, response),
        ]
    events += [e("reply.invalidated", 105, "failed"), e("audio.ack", 390, "later")]
    result = analyze(reversed(events))
    first, unanswered = result["turns"]
    assert first["first_response_id"] == "retry"
    assert first["speech_end_to_first_sent_ms"] == 170
    assert first["speech_end_to_first_ack_ms"] == 380
    assert first["first_ack_response_id"] == "later"
    assert unanswered["first_response_id"] is None
    retry = next(r for r in result["responses"] if r["response_id"] == "retry")
    assert [
        retry[k] for k in ("dispatch_wait_ms", "tts_queue_ms", "tts_first_packet_synthesis_ms", "tts_delivery_ms")
    ] == [10, 20, 40, 5]
    assert retry["tts_full_synthesis_ms"] is None


def test_retrieval_phases_join_tool_and_model_continuation_without_cross_process_leak():
    def e(name, ms, **fields):
        return dict(event=name, monotonic_ns=ms * 1_000_000, call_id="call", **{"process_run": "run", **fields})

    phases = {"embedding": {"duration_ms": 12, "count": 1, "status": "success"}}
    result = analyze(
        [
            e("retrieval.tool_requested", 1, response_id="parent", tool_call_id="tool", turn_seq=1),
            e(
                "retrieval.phases",
                20,
                response_id="parent",
                tool_call_id="tool",
                turn_seq=1,
                phases=phases,
                status="success",
            ),
            e("retrieval.tool_completed", 22, response_id="parent", tool_call_id="tool"),
            e("retrieval.tool_submitted", 24, response_id="parent", tool_call_id="tool"),
            e("reply.continuation_requested", 24, response_id="parent"),
            e("reply.first_text_delta", 28, response_id="child"),
            e("reply.model_link", 25, response_id="child", parent_response_id="parent"),
            e("reply.generation_started", 25, response_id="child"),
            e("reply.segment_ready", 35, response_id="child"),
            e("reply.generation_finished", 45, response_id="child"),
            e("retrieval.phases", 99, process_run="other", tool_call_id="tool", status="error", phases={}),
        ]
    )
    retrieval = next(r for r in result["retrievals"] if r["process_run"] == "run")
    assert retrieval["phases"] == phases
    assert retrieval["tool_ms"] == 21 and retrieval["submit_ms"] == 2
    assert retrieval["turn_seq"] == 1 and retrieval["model_response_id"] == "parent"
    assert result["model_responses"][0]["parent_response_id"] == "parent"
    model = result["model_responses"][0]
    assert model["first_segment_ms"] == 10
    assert (
        model["first_text_delta_ms"],
        model["first_delta_to_segment_ms"],
        model["continuation_to_first_text_delta_ms"],
    ) == (3, 7, 4)


def test_playback_feedback_joins_stop_sequence_and_keeps_acoustic_estimate_separate():
    def e(name, ms, **fields):
        return dict(event=name, monotonic_ns=ms * 1_000_000, process_run="run", call_id="c", **fields)

    data = [
        e("input.provider_speech_stopped", 100, turn_seq=1, estimated_end_ns=40_000_000),
        e("reply.response", 110, turn_seq=1, response_id="r"),
        e("audio.sent", 150, response_id="r"),
        e("audio.ack", 180, response_id="r"),
        e("input.speech_started", 200, item_id="next"),
        e("reply.interrupt", 201, response_id="r", item_id="next"),
        e("audio.stop_requested", 204, response_id="r", stream_id=2, stop_seq=5),
        e("audio.stop_requested", 208, response_id="r", stream_id=3, stop_seq=6),
        e("audio.stop_confirmed", 218, response_id="r", stream_id=3, stop_seq=6, accepted=True),
    ]
    row = analyze(reversed(data))["responses"][0]
    assert row["estimated_end_to_provider_stop_ms"] == 60
    assert row["estimated_end_to_first_ack_ms"] == 140
    first, second = row["stop_confirmations"]
    assert first["confirmation_ms"] is None
    assert second["confirmation_ms"] == 10
    assert second["speech_started_to_confirmation_ms"] == 18
