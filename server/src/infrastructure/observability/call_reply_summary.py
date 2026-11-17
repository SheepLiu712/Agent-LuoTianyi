"""将通话回复阶段记录聚合为控制台统计；缺失阶段保持缺失。"""

import json

PHASES = (
    "endpointing",
    "scheduling",
    "retrieval",
    "retrieval.authorization",
    "retrieval.queue",
    "retrieval.embedding",
    "retrieval.vector_search",
    "retrieval.hydration",
    "retrieval.materialization",
    "generation_queue",
    "generation",
    "submission",
    "dispatch_wait",
    "tts_queue",
    "tts_synthesis",
    "tts_delivery",
    "tts_first_packet",
    "first_sent",
    "first_ack",
    "legacy_first_generated",
    "total",
)


def summarize_call_replies(rows, summarize_values, limit):
    attempts = {}
    values = {phase: [] for phase in PHASES}
    failures = {phase: 0 for phase in PHASES}
    for row in rows:
        metadata = json.loads(row["metadata_json"] or "{}")
        request_id = metadata.get("reply_request_id")
        if not request_id:
            continue
        key = (row["trace_id"], request_id)
        attempt = attempts.setdefault(
            key,
            {
                "trace_id": row["trace_id"],
                "request_id": request_id,
                "turn_seq": metadata.get("turn_seq"),
                "started_at": row["start_ts"],
                "speech_end_basis": metadata.get("speech_end_basis"),
                "outcome": "incomplete",
                "phases": {},
                "model_response_id": metadata.get("model_response_id"),
                "deliveries": [],
                "invalidated": [],
            },
        )
        phase = row["span_name"].removeprefix("call.reply.")
        if phase in {"first_sent", "first_ack"}:
            attempt["deliveries"].append(
                {
                    "phase": phase,
                    "delivery_id": metadata["delivery_id"],
                    "end_ts": row["end_ts"],
                    "duration_ms": float(row["duration_ms"]),
                }
            )
        if phase == "invalidated":
            attempt["invalidated"].append(metadata["delivery_id"])
        if phase == "total":
            if attempt["model_response_id"] is None:
                _collect_phase(attempt, "legacy_first_generated", row, metadata, values, failures)
        else:
            _collect_phase(attempt, phase, row, metadata, values, failures)
    for attempt in attempts.values():
        if "first_ack" in attempt["phases"]:
            attempt["phases"]["total"] = attempt["phases"]["first_ack"]
    turns = _first_deliveries(attempts.values(), "first_ack")
    values["total"].extend(row["duration_ms"] for row in turns)

    return {
        "total_measurement": "provider_speech_stopped_to_first_audio_ack_proxy",
        "turns": turns,
        "sent_turns": _first_deliveries(attempts.values(), "first_sent"),
        "attempt_count": len(attempts),
        "completed_count": sum(a["outcome"] == "completed" for a in attempts.values()),
        "summary": {
            phase: {**summarize_values(items), "failed_count": failures[phase]} for phase, items in values.items()
        },
        "recent": sorted(attempts.values(), key=lambda a: a["started_at"], reverse=True)[:limit],
    }


def _collect_phase(attempt, phase, row, metadata, values, failures):
    if phase == "terminal":
        attempt["outcome"] = metadata["outcome"]
    if phase not in values or phase in attempt["phases"]:
        return
    duration = float(row["duration_ms"])
    attempt["phases"][phase] = {"duration_ms": duration, "status": row["status"]}
    if row["status"] == "success":
        if phase != "total" or attempt["model_response_id"] is None:
            values[phase].append(duration)
    else:
        failures[phase] += 1


def _first_deliveries(attempts, phase):
    turns = {}
    for attempt in attempts:
        if attempt["model_response_id"] is None or attempt["turn_seq"] is None:
            continue
        for delivery in attempt["deliveries"]:
            if delivery["phase"] != phase or (
                phase == "first_sent" and delivery["delivery_id"] in attempt["invalidated"]
            ):
                continue
            key = (attempt["trace_id"], attempt["turn_seq"])
            row = {**delivery, "trace_id": key[0], "turn_seq": key[1]}
            if key not in turns or row["duration_ms"] < turns[key]["duration_ms"]:
                turns[key] = row
    return list(turns.values())
