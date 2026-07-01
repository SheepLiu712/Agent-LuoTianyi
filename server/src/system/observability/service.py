from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import traceback
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from uuid import uuid4


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return json.dumps({"unserializable": str(value)}, ensure_ascii=False)


def _json_loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def new_trace_id(prefix: str = "trace") -> str:
    return f"{prefix}-{uuid4().hex[:16]}"


_current_trace_id: ContextVar[str | None] = ContextVar("observability_trace_id", default=None)
_current_user_id: ContextVar[str | None] = ContextVar("observability_user_id", default=None)
_current_topic_id: ContextVar[str | None] = ContextVar("observability_topic_id", default=None)


def get_trace_context() -> dict[str, str | None]:
    return {
        "trace_id": _current_trace_id.get(),
        "user_id": _current_user_id.get(),
        "topic_id": _current_topic_id.get(),
    }


@dataclass
class SpanTimer:
    service: "ObservabilityService | None"
    trace_id: str
    span_name: str
    user_id: str | None = None
    topic_id: str | None = None
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        self._start_monotonic = time.perf_counter()
        self._start_ts = _utc_now_iso()
        self._status = "success"
        self._error: str | None = None
        self._trace_token = _current_trace_id.set(self.trace_id)
        self._user_token = _current_user_id.set(self.user_id)
        self._topic_token = _current_topic_id.set(self.topic_id)

    def fail(self, exc: BaseException) -> None:
        self._status = "error"
        self._error = f"{exc.__class__.__name__}: {exc}"

    def finish(self, *, extra_metadata: dict[str, Any] | None = None) -> None:
        try:
            if self.service is None:
                return
            metadata = dict(self.metadata or {})
            if extra_metadata:
                metadata.update(extra_metadata)
            if self._error:
                metadata["error"] = self._error
            self.service.record_pipeline_span(
                trace_id=self.trace_id,
                span_name=self.span_name,
                start_ts=self._start_ts,
                end_ts=_utc_now_iso(),
                duration_ms=(time.perf_counter() - self._start_monotonic) * 1000.0,
                user_id=self.user_id,
                topic_id=self.topic_id,
                status=self._status,
                metadata=metadata,
            )
        finally:
            _current_trace_id.reset(self._trace_token)
            _current_user_id.reset(self._user_token)
            _current_topic_id.reset(self._topic_token)


class ObservabilityService:
    """SQLite-backed first-phase metrics store for the admin console."""

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        config = config or {}
        db_path = config.get("db_path") or os.path.join("data", "admin_metrics.sqlite3")
        self.db_path = Path(db_path)
        if not self.db_path.is_absolute():
            self.db_path = Path.cwd() / self.db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.retention_days = int(config.get("retention_days", 30))
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._initialize_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def span(
        self,
        *,
        trace_id: str,
        span_name: str,
        user_id: str | None = None,
        topic_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        timer = SpanTimer(
            service=self,
            trace_id=trace_id,
            span_name=span_name,
            user_id=user_id,
            topic_id=topic_id,
            metadata=metadata,
        )
        try:
            yield timer
        except Exception as exc:
            timer.fail(exc)
            raise
        finally:
            timer.finish()

    def record_llm_call(
        self,
        *,
        module_name: str,
        interface_name: str | None,
        model_name: str | None,
        latency_ms: float,
        success: bool,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        error_type: str | None = None,
        error_message: str | None = None,
        trace_id: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._execute(
            """
            INSERT INTO llm_call_metrics (
                ts, trace_id, user_id, module_name, interface_name, model_name,
                prompt_tokens, completion_tokens, total_tokens, latency_ms,
                success, error_type, error_message, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utc_now_iso(),
                trace_id,
                user_id,
                module_name,
                interface_name,
                model_name,
                int(prompt_tokens or 0),
                int(completion_tokens or 0),
                int(total_tokens or 0),
                float(latency_ms or 0.0),
                1 if success else 0,
                error_type,
                error_message,
                _json_dumps(metadata or {}),
            ),
        )

    def record_pipeline_span(
        self,
        *,
        trace_id: str,
        span_name: str,
        start_ts: str,
        end_ts: str,
        duration_ms: float,
        user_id: str | None = None,
        topic_id: str | None = None,
        status: str = "success",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._execute(
            """
            INSERT INTO pipeline_spans (
                trace_id, user_id, topic_id, span_name,
                start_ts, end_ts, duration_ms, status, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace_id,
                user_id,
                topic_id,
                span_name,
                start_ts,
                end_ts,
                float(duration_ms or 0.0),
                status,
                _json_dumps(metadata or {}),
            ),
        )

    def record_log_event(
        self,
        *,
        level: str,
        logger_name: str,
        message: str,
        traceback_text: str | None = None,
        trace_id: str | None = None,
        user_id: str | None = None,
        module_name: str | None = None,
    ) -> None:
        self._execute(
            """
            INSERT INTO admin_log_events (
                ts, level, logger_name, message, traceback, trace_id, user_id, module_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utc_now_iso(),
                level,
                logger_name,
                message,
                traceback_text,
                trace_id,
                user_id,
                module_name,
            ),
        )

    def record_memory_trace_event(
        self,
        *,
        trace_id: str | None,
        user_id: str | None,
        event_type: str,
        item_type: str,
        topic_id: str | None = None,
        command_text: str | None = None,
        content_text: str | None = None,
        source_context: str | None = None,
        result: dict[str, Any] | list[Any] | None = None,
        duration_ms: float | None = None,
        annotation_required: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._execute(
            """
            INSERT INTO memory_trace_events (
                ts, trace_id, user_id, topic_id, event_type, item_type,
                command_text, content_text, source_context, result_json,
                duration_ms, annotation_required, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utc_now_iso(),
                trace_id,
                user_id,
                topic_id,
                event_type,
                item_type,
                command_text,
                content_text,
                source_context,
                _json_dumps(result or {}),
                float(duration_ms or 0.0),
                1 if annotation_required else 0,
                _json_dumps(metadata or {}),
            ),
        )

    def get_dashboard_summary(self, *, days: int = 1) -> Dict[str, Any]:
        since = self._since_iso(days)
        llm = self._query_one(
            """
            SELECT
                COUNT(*) AS call_count,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                COALESCE(AVG(latency_ms), 0) AS avg_latency_ms,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed_calls
            FROM llm_call_metrics
            WHERE ts >= ?
            """,
            (since,),
        )
        spans = self.get_pipeline_latency_summary(days=days)
        logs = self._query_one(
            """
            SELECT
                SUM(CASE WHEN level = 'WARNING' THEN 1 ELSE 0 END) AS warning_count,
                SUM(CASE WHEN level IN ('ERROR', 'CRITICAL') THEN 1 ELSE 0 END) AS error_count
            FROM admin_log_events
            WHERE ts >= ?
            """,
            (since,),
        )
        return {
            "window_days": days,
            "llm": llm,
            "pipeline": spans,
            "logs": logs,
            "recent_logs": self.get_recent_logs(limit=10, min_level="WARNING"),
            "slow_spans": self.get_recent_pipeline_spans(limit=10, order_by_slow=True),
        }

    def get_llm_summary(self, *, days: int = 7) -> Dict[str, Any]:
        since = self._since_iso(days)
        totals = self._query_one(
            """
            SELECT
                COUNT(*) AS call_count,
                COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(AVG(prompt_tokens), 0) AS avg_prompt_tokens,
                COALESCE(AVG(completion_tokens), 0) AS avg_completion_tokens,
                COALESCE(AVG(total_tokens), 0) AS avg_total_tokens,
                COALESCE(AVG(latency_ms), 0) AS avg_latency_ms,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed_calls
            FROM llm_call_metrics
            WHERE ts >= ?
            """,
            (since,),
        )
        by_module = self._query_all(
            """
            SELECT module_name, interface_name, model_name,
                COUNT(*) AS call_count,
                COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(AVG(prompt_tokens), 0) AS avg_prompt_tokens,
                COALESCE(AVG(completion_tokens), 0) AS avg_completion_tokens,
                COALESCE(AVG(total_tokens), 0) AS avg_total_tokens,
                COALESCE(AVG(latency_ms), 0) AS avg_latency_ms,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed_calls
            FROM llm_call_metrics
            WHERE ts >= ?
            GROUP BY module_name, interface_name, model_name
            ORDER BY call_count DESC
            """,
            (since,),
        )
        daily = self._query_all(
            """
            SELECT substr(ts, 1, 10) AS day,
                COUNT(*) AS call_count,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(AVG(total_tokens), 0) AS avg_total_tokens,
                COALESCE(AVG(latency_ms), 0) AS avg_latency_ms
            FROM llm_call_metrics
            WHERE ts >= ?
            GROUP BY substr(ts, 1, 10)
            ORDER BY day
            """,
            (since,),
        )
        return {"window_days": days, "totals": totals, "by_module": by_module, "daily": daily}

    def get_pipeline_latency_summary(self, *, days: int = 7) -> Dict[str, Any]:
        since = self._since_iso(days)
        rows = self._query_all(
            """
            SELECT span_name, duration_ms
            FROM pipeline_spans
            WHERE start_ts >= ?
            ORDER BY span_name, duration_ms
            """,
            (since,),
        )
        grouped: dict[str, list[float]] = {}
        for row in rows:
            grouped.setdefault(row["span_name"], []).append(float(row["duration_ms"] or 0.0))
        return {
            span_name: self._summarize_values(values)
            for span_name, values in grouped.items()
        }

    def get_recent_pipeline_spans(
        self,
        *,
        limit: int = 50,
        trace_id: str | None = None,
        order_by_slow: bool = False,
    ) -> list[dict[str, Any]]:
        where = ""
        params: list[Any] = []
        if trace_id:
            where = "WHERE trace_id = ?"
            params.append(trace_id)
        order = "duration_ms DESC" if order_by_slow else "start_ts DESC"
        params.append(limit)
        rows = self._query_all(
            f"""
            SELECT *
            FROM pipeline_spans
            {where}
            ORDER BY {order}
            LIMIT ?
            """,
            tuple(params),
        )
        return [self._decode_metadata(row) for row in rows]

    def get_recent_llm_calls(
        self,
        *,
        limit: int = 100,
        module_name: str | None = None,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if module_name:
            conditions.append("module_name = ?")
            params.append(module_name)
        if trace_id:
            conditions.append("trace_id = ?")
            params.append(trace_id)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        rows = self._query_all(
            f"""
            SELECT *
            FROM llm_call_metrics
            {where}
            ORDER BY ts DESC
            LIMIT ?
            """,
            tuple(params),
        )
        return [self._decode_metadata(row) for row in rows]

    def get_trace_summaries(self, *, days: int = 7, limit: int = 100) -> list[dict[str, Any]]:
        since = self._since_iso(days)
        span_rows = self._query_all(
            """
            SELECT trace_id,
                MAX(user_id) AS user_id,
                MAX(topic_id) AS topic_id,
                MIN(start_ts) AS start_ts,
                MAX(end_ts) AS end_ts,
                COUNT(*) AS span_count,
                COALESCE(SUM(duration_ms), 0) AS total_span_ms,
                COALESCE(MAX(duration_ms), 0) AS max_span_ms
            FROM pipeline_spans
            WHERE start_ts >= ? AND trace_id IS NOT NULL AND trace_id != ''
            GROUP BY trace_id
            """,
            (since,),
        )
        llm_rows = self._query_all(
            """
            SELECT trace_id,
                MAX(user_id) AS user_id,
                MIN(ts) AS first_llm_ts,
                MAX(ts) AS last_llm_ts,
                COUNT(*) AS llm_call_count,
                COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(latency_ms), 0) AS total_llm_latency_ms,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed_llm_calls
            FROM llm_call_metrics
            WHERE ts >= ? AND trace_id IS NOT NULL AND trace_id != ''
            GROUP BY trace_id
            """,
            (since,),
        )
        traces: dict[str, dict[str, Any]] = {}
        for row in span_rows:
            traces[row["trace_id"]] = {
                "trace_id": row["trace_id"],
                "user_id": row.get("user_id"),
                "topic_id": row.get("topic_id"),
                "start_ts": row.get("start_ts"),
                "end_ts": row.get("end_ts"),
                "duration_ms": self._duration_between(row.get("start_ts"), row.get("end_ts")),
                "span_count": int(row.get("span_count") or 0),
                "total_span_ms": float(row.get("total_span_ms") or 0.0),
                "max_span_ms": float(row.get("max_span_ms") or 0.0),
                "llm_call_count": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "total_llm_latency_ms": 0.0,
                "failed_llm_calls": 0,
            }
        for row in llm_rows:
            trace = traces.setdefault(
                row["trace_id"],
                {
                    "trace_id": row["trace_id"],
                    "user_id": row.get("user_id"),
                    "topic_id": None,
                    "start_ts": row.get("first_llm_ts"),
                    "end_ts": row.get("last_llm_ts"),
                    "span_count": 0,
                    "total_span_ms": 0.0,
                    "max_span_ms": 0.0,
                },
            )
            if not trace.get("user_id"):
                trace["user_id"] = row.get("user_id")
            trace["start_ts"] = self._min_iso(trace.get("start_ts"), row.get("first_llm_ts"))
            trace["end_ts"] = self._max_iso(trace.get("end_ts"), row.get("last_llm_ts"))
            trace["duration_ms"] = self._duration_between(trace.get("start_ts"), trace.get("end_ts"))
            trace["llm_call_count"] = int(row.get("llm_call_count") or 0)
            trace["prompt_tokens"] = int(row.get("prompt_tokens") or 0)
            trace["completion_tokens"] = int(row.get("completion_tokens") or 0)
            trace["total_tokens"] = int(row.get("total_tokens") or 0)
            trace["total_llm_latency_ms"] = float(row.get("total_llm_latency_ms") or 0.0)
            trace["failed_llm_calls"] = int(row.get("failed_llm_calls") or 0)
        return sorted(
            traces.values(),
            key=lambda row: row.get("end_ts") or row.get("start_ts") or "",
            reverse=True,
        )[:limit]

    def get_trace_detail(self, trace_id: str) -> dict[str, Any]:
        summaries = [
            row for row in self.get_trace_summaries(days=self.retention_days, limit=10000)
            if row.get("trace_id") == trace_id
        ]
        spans = self.get_recent_pipeline_spans(limit=1000, trace_id=trace_id)
        spans.sort(key=lambda row: row.get("start_ts") or "")
        llm_calls = self.get_recent_llm_calls(limit=1000, trace_id=trace_id)
        llm_calls.sort(key=lambda row: row.get("ts") or "")
        return {
            "summary": summaries[0] if summaries else {"trace_id": trace_id},
            "spans": spans,
            "llm_calls": llm_calls,
        }

    def get_memory_trace_events(
        self,
        *,
        days: int = 7,
        limit: int = 200,
        trace_id: str | None = None,
        event_type: str | None = None,
        annotation_state: str | None = None,
    ) -> list[dict[str, Any]]:
        since = self._since_iso(days)
        conditions = ["e.ts >= ?"]
        params: list[Any] = [since]
        if trace_id:
            conditions.append("e.trace_id = ?")
            params.append(trace_id)
        if event_type:
            event_types = [item.strip() for item in event_type.split(",") if item.strip()]
            if event_types:
                placeholders = ", ".join("?" for _ in event_types)
                conditions.append(f"e.event_type IN ({placeholders})")
                params.extend(event_types)
        if annotation_state == "pending":
            conditions.append("e.annotation_required = 1 AND a.event_id IS NULL")
        elif annotation_state == "annotated":
            conditions.append("a.event_id IS NOT NULL")
        params.append(limit)
        rows = self._query_all(
            f"""
            SELECT e.*, a.label AS annotation_label, a.notes AS annotation_notes,
                a.annotator AS annotation_annotator, a.updated_at AS annotation_updated_at
            FROM memory_trace_events e
            LEFT JOIN memory_trace_annotations a ON a.event_id = e.id
            WHERE {' AND '.join(conditions)}
            ORDER BY e.ts DESC
            LIMIT ?
            """,
            tuple(params),
        )
        return [self._decode_memory_event(row) for row in rows]

    def get_memory_trace_summary(self, *, days: int = 7) -> dict[str, Any]:
        since = self._since_iso(days)
        totals = self._query_one(
            """
            SELECT
                COUNT(*) AS event_count,
                SUM(CASE WHEN annotation_required = 1 THEN 1 ELSE 0 END) AS annotation_required_count,
                SUM(CASE WHEN annotation_required = 1 AND a.event_id IS NULL THEN 1 ELSE 0 END) AS pending_annotation_count,
                SUM(CASE WHEN a.event_id IS NOT NULL THEN 1 ELSE 0 END) AS annotated_count
            FROM memory_trace_events e
            LEFT JOIN memory_trace_annotations a ON a.event_id = e.id
            WHERE e.ts >= ?
            """,
            (since,),
        )
        by_type = self._query_all(
            """
            SELECT e.event_type, e.item_type,
                COUNT(*) AS event_count,
                SUM(CASE WHEN e.annotation_required = 1 AND a.event_id IS NULL THEN 1 ELSE 0 END) AS pending_annotation_count,
                COALESCE(AVG(e.duration_ms), 0) AS avg_duration_ms,
                COALESCE(MAX(e.duration_ms), 0) AS max_duration_ms
            FROM memory_trace_events e
            LEFT JOIN memory_trace_annotations a ON a.event_id = e.id
            WHERE e.ts >= ?
            GROUP BY e.event_type, e.item_type
            ORDER BY event_count DESC
            """,
            (since,),
        )
        return {"window_days": days, "totals": totals, "by_type": by_type}

    def annotate_memory_trace_event(
        self,
        event_id: int,
        *,
        label: str,
        notes: str | None = None,
        annotator: str | None = None,
    ) -> dict[str, Any]:
        updated_at = _utc_now_iso()
        self._execute(
            """
            INSERT INTO memory_trace_annotations (
                event_id, label, notes, annotator, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                label = excluded.label,
                notes = excluded.notes,
                annotator = excluded.annotator,
                updated_at = excluded.updated_at
            """,
            (event_id, label, notes, annotator, updated_at),
        )
        return {
            "event_id": event_id,
            "label": label,
            "notes": notes,
            "annotator": annotator,
            "updated_at": updated_at,
        }

    def get_recent_logs(
        self,
        *,
        limit: int = 100,
        min_level: str | None = None,
    ) -> list[dict[str, Any]]:
        levels = {
            "DEBUG": 10,
            "INFO": 20,
            "WARNING": 30,
            "ERROR": 40,
            "CRITICAL": 50,
        }
        rows = self._query_all(
            """
            SELECT *
            FROM admin_log_events
            ORDER BY ts DESC
            LIMIT ?
            """,
            (max(limit * 3, limit),),
        )
        if min_level:
            threshold = levels.get(min_level.upper(), 0)
            rows = [row for row in rows if levels.get(str(row["level"]).upper(), 0) >= threshold]
        return [dict(row) for row in rows[:limit]]

    def cleanup_old_records(self) -> None:
        if self.retention_days <= 0:
            return
        cutoff = self._since_iso(self.retention_days)
        for table, column in (
            ("llm_call_metrics", "ts"),
            ("pipeline_spans", "start_ts"),
            ("admin_log_events", "ts"),
            ("memory_trace_events", "ts"),
        ):
            self._execute(f"DELETE FROM {table} WHERE {column} < ?", (cutoff,))

    def _initialize_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS llm_call_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    trace_id TEXT,
                    user_id TEXT,
                    module_name TEXT NOT NULL,
                    interface_name TEXT,
                    model_name TEXT,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    latency_ms REAL NOT NULL DEFAULT 0,
                    success INTEGER NOT NULL DEFAULT 1,
                    error_type TEXT,
                    error_message TEXT,
                    metadata_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_llm_ts ON llm_call_metrics(ts);
                CREATE INDEX IF NOT EXISTS idx_llm_module ON llm_call_metrics(module_name, ts);
                CREATE INDEX IF NOT EXISTS idx_llm_trace ON llm_call_metrics(trace_id);

                CREATE TABLE IF NOT EXISTS pipeline_spans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL,
                    user_id TEXT,
                    topic_id TEXT,
                    span_name TEXT NOT NULL,
                    start_ts TEXT NOT NULL,
                    end_ts TEXT NOT NULL,
                    duration_ms REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'success',
                    metadata_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_span_trace ON pipeline_spans(trace_id);
                CREATE INDEX IF NOT EXISTS idx_span_name_ts ON pipeline_spans(span_name, start_ts);

                CREATE TABLE IF NOT EXISTS admin_log_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    level TEXT NOT NULL,
                    logger_name TEXT NOT NULL,
                    message TEXT NOT NULL,
                    traceback TEXT,
                    trace_id TEXT,
                    user_id TEXT,
                    module_name TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_log_ts ON admin_log_events(ts);
                CREATE INDEX IF NOT EXISTS idx_log_level_ts ON admin_log_events(level, ts);

                CREATE TABLE IF NOT EXISTS memory_trace_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    trace_id TEXT,
                    user_id TEXT,
                    topic_id TEXT,
                    event_type TEXT NOT NULL,
                    item_type TEXT NOT NULL,
                    command_text TEXT,
                    content_text TEXT,
                    source_context TEXT,
                    result_json TEXT,
                    duration_ms REAL NOT NULL DEFAULT 0,
                    annotation_required INTEGER NOT NULL DEFAULT 1,
                    metadata_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_memory_trace_ts ON memory_trace_events(ts);
                CREATE INDEX IF NOT EXISTS idx_memory_trace_trace ON memory_trace_events(trace_id);
                CREATE INDEX IF NOT EXISTS idx_memory_trace_type ON memory_trace_events(event_type, item_type, ts);

                CREATE TABLE IF NOT EXISTS memory_trace_annotations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER NOT NULL UNIQUE,
                    label TEXT NOT NULL,
                    notes TEXT,
                    annotator TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(event_id) REFERENCES memory_trace_events(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_memory_annotation_label ON memory_trace_annotations(label);
                """
            )
            self._conn.commit()

    def _execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self._lock:
            self._conn.execute(sql, tuple(params))
            self._conn.commit()

    def _query_one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any]:
        rows = self._query_all(sql, params)
        return rows[0] if rows else {}

    def _query_all(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            return [dict(row) for row in cur.fetchall()]

    def _since_iso(self, days: int) -> str:
        return (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat(timespec="milliseconds")

    def _decode_metadata(self, row: dict[str, Any]) -> dict[str, Any]:
        row = dict(row)
        row["metadata"] = _json_loads(row.pop("metadata_json", None), {})
        return row

    def _decode_memory_event(self, row: dict[str, Any]) -> dict[str, Any]:
        row = self._decode_metadata(row)
        row["result"] = _json_loads(row.pop("result_json", None), {})
        row["annotation_required"] = bool(row.get("annotation_required"))
        return row

    def _summarize_values(self, values: list[float]) -> dict[str, Any]:
        if not values:
            return {"count": 0, "avg_ms": 0, "p50_ms": 0, "p90_ms": 0, "p99_ms": 0, "max_ms": 0}
        values = sorted(values)
        return {
            "count": len(values),
            "avg_ms": sum(values) / len(values),
            "p50_ms": self._percentile(values, 50),
            "p90_ms": self._percentile(values, 90),
            "p99_ms": self._percentile(values, 99),
            "max_ms": values[-1],
        }

    @staticmethod
    def _percentile(values: list[float], percentile: int) -> float:
        if not values:
            return 0.0
        if len(values) == 1:
            return values[0]
        rank = (len(values) - 1) * percentile / 100.0
        lower = int(rank)
        upper = min(lower + 1, len(values) - 1)
        weight = rank - lower
        return values[lower] * (1 - weight) + values[upper] * weight

    def _duration_between(self, start_ts: str | None, end_ts: str | None) -> float:
        start = self._parse_iso(start_ts)
        end = self._parse_iso(end_ts)
        if start is None or end is None:
            return 0.0
        return max(0.0, (end - start).total_seconds() * 1000)

    @staticmethod
    def _parse_iso(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _min_iso(left: str | None, right: str | None) -> str | None:
        if not left:
            return right
        if not right:
            return left
        return min(left, right)

    @staticmethod
    def _max_iso(left: str | None, right: str | None) -> str | None:
        if not left:
            return right
        if not right:
            return left
        return max(left, right)


_observability_service: ObservabilityService | None = None


def set_observability_service(service: ObservabilityService | None) -> None:
    global _observability_service
    _observability_service = service


def get_observability_service() -> ObservabilityService | None:
    return _observability_service


def record_exception_log(logger_name: str, level: str, message: str, exc_info: Any = None) -> None:
    service = get_observability_service()
    if service is None:
        return
    traceback_text = None
    if exc_info:
        if exc_info is True:
            traceback_text = traceback.format_exc()
        elif isinstance(exc_info, tuple):
            traceback_text = "".join(traceback.format_exception(*exc_info))
    service.record_log_event(
        level=level,
        logger_name=logger_name,
        message=message,
        traceback_text=traceback_text,
    )
