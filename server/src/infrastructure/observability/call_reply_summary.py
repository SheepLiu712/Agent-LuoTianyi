"""将通话回复阶段记录聚合为控制台统计；缺失阶段保持缺失。"""

import json

PHASES = (
    "endpointing",
    "scheduling",
    "retrieval",
    "generation_queue",
    "generation",
    "submission",
    "tts_first_packet",
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
            },
        )
        phase = row["span_name"].removeprefix("call.reply.")
        _collect_phase(attempt, phase, row, metadata, values, failures)
    return {
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
        values[phase].append(duration)
    else:
        failures[phase] += 1
