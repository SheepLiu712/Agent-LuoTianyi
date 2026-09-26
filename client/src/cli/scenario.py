"""场景引擎与报告（S9 契约）。

- 场景文件：{"actions": [动作信封...], "on_failure": "stop_side_effects" | "continue"}
- 失败后默认只继续只读白名单动作，其余动作记为 skipped（不贡献退出码）。
- 报告默认仅脱敏元数据（data_keys）；include_content=True 时改为完整脱敏 data。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .actions import ExitCode

READ_ONLY_ACTIONS = frozenset(
    {
        "session.status",
        "history.initial",
        "history.load",
        "events.read",
        "events.wait",
        "reply.read",
        "reply.wait",
        "preferences.read",
        "dynamics.read",
        "dynamics.load",
        "audio.replay",
        "session.close",
    }
)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _record(executor, action: str, status: str, data: dict, error) -> dict:
    return {
        "schema_version": "1.0",
        "timestamp": _timestamp(),
        "session_id": executor.session_id,
        "action_id": f"a-{uuid.uuid4().hex[:12]}",
        "action": action,
        "event": "action_result",
        "status": status,
        "duration_ms": 0,
        "correlation_id": None,
        "data": data,
        "error": error,
    }


def _invalid_scenario(executor, emit, message: str) -> int:
    emit(
        _record(
            executor,
            "scenario.run",
            "failed",
            {},
            {"code": "INVALID_SCENARIO", "message": message, "category": "input"},
        )
    )
    return int(ExitCode.INPUT_ERROR)


def _validate_scenario(source):
    if source is None:
        raise ValueError("scenario source is missing or unreadable")
    try:
        scenario = json.loads(source)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid scenario JSON: {exc}") from exc
    if not isinstance(scenario, dict):
        raise ValueError("scenario must be a JSON object")
    actions = scenario.get("actions")
    if not isinstance(actions, list) or not actions:
        raise ValueError("scenario.actions must be a non-empty list")
    for entry in actions:
        if not isinstance(entry, dict):
            raise ValueError("each scenario action must be an object")
        action = entry.get("action")
        if not isinstance(action, str) or not action.strip():
            raise ValueError("each scenario action needs a non-empty action name")
    on_failure = scenario.get("on_failure", "stop_side_effects")
    if on_failure not in ("stop_side_effects", "continue"):
        raise ValueError("scenario.on_failure must be 'stop_side_effects' or 'continue'")
    return actions, on_failure


def _write_report(
    path,
    records: list,
    counts: dict,
    started: str,
    finished: str,
    exit_code: int,
    include_content: bool,
    redactor,
) -> None:
    actions_report = []
    for record in records:
        data = record.get("data") or {}
        item = {
            "action": record.get("action"),
            "status": record.get("status"),
            "duration_ms": record.get("duration_ms"),
            "correlation_id": record.get("correlation_id"),
            "error": record.get("error"),
        }
        if include_content:
            item["data"] = data
        else:
            item["data_keys"] = list(data.keys())
        actions_report.append(item)
    report = {
        "schema_version": "1.0",
        "started_at": started,
        "finished_at": finished,
        "exit_code": exit_code,
        "summary": {**counts, "action_count": sum(counts.values())},
        "actions": actions_report,
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(redactor.redact(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run_scenario(
    executor,
    source,
    emit,
    *,
    report_path=None,
    include_content: bool = False,
) -> int:
    try:
        actions, on_failure = _validate_scenario(source)
    except ValueError as exc:
        return _invalid_scenario(executor, emit, str(exc))

    started = _timestamp()
    counts = {"passed": 0, "failed": 0, "timed_out": 0, "skipped": 0, "suppressed": 0}
    records: list = []
    final_exit = int(ExitCode.SUCCESS)
    failed_once = False
    for envelope in actions:
        action = envelope["action"].strip()
        if failed_once and on_failure == "stop_side_effects" and action not in READ_ONLY_ACTIONS:
            skipped = _record(executor, action, "skipped", {"reason": "after_failure"}, None)
            emit(skipped)
            counts["skipped"] += 1
            records.append(skipped)
            continue
        record, exit_code = executor.execute(envelope)
        emit(record)
        status = record.get("status")
        if status in counts:
            counts[status] += 1
        if exit_code != 0:
            failed_once = True
            final_exit = max(final_exit, int(exit_code))
        records.append(record)

    finished = _timestamp()
    summary_error = None
    if report_path is not None:
        try:
            _write_report(
                report_path,
                records,
                counts,
                started,
                finished,
                final_exit,
                include_content,
                executor.redactor,
            )
        except OSError as exc:
            summary_error = {
                "code": "REPORT_WRITE_FAILED",
                "message": str(exc),
                "category": "input",
            }
            final_exit = max(final_exit, int(ExitCode.INPUT_ERROR))
    summary_data = {
        "action_count": len(actions),
        **counts,
        "exit_code": final_exit,
    }
    summary = _record(
        executor,
        "scenario.run",
        "passed" if final_exit == 0 else "failed",
        summary_data,
        summary_error,
    )
    summary["event"] = "scenario_result"
    emit(summary)
    return final_exit
