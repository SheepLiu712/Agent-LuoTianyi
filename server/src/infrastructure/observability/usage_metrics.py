"""Continuous usage buckets and curated latency groups for the admin console."""

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

CHAT = (
    ("input", "输入准备"),
    ("wait", "等待回复"),
    ("topic", "主题与意图提取"),
    ("retrieval", "记忆检索"),
    ("generation", "LLM 首段回复"),
    ("delivery", "首段回复交付"),
    ("total", "回复首段总耗时"),
)
CALL = (
    ("ack", "供应商判停至首个音频 ACK"),
    ("endpointing", "判断说话结束（估计）"),
    ("retrieval", "记忆检索"),
    ("generation", "LLM 启动至首段回复"),
    ("tts", "首段回复至 TTS 首包产出"),
)


def window_start(window, now):
    if window not in {"24h", "7d", "all"}:
        raise ValueError("window must be 24h, 7d or all")
    return now - timedelta(days=1 if window == "24h" else 7) if window != "all" else None


class UsageMetricsStore:
    def initialize_usage_schema(self):
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS stage_population_samples (
                    sampled_at TEXT NOT NULL, runtime_id TEXT NOT NULL,
                    scope_count INTEGER NOT NULL, chat_stage_count INTEGER NOT NULL,
                    call_stage_count INTEGER NOT NULL, overlap_count INTEGER NOT NULL,
                    terminating_stage_count INTEGER NOT NULL,
                    PRIMARY KEY(sampled_at, runtime_id)
                );
                CREATE TABLE IF NOT EXISTS tts_requests (
                    request_id TEXT PRIMARY KEY, requested_at TEXT NOT NULL,
                    user_id TEXT, character_id TEXT NOT NULL, interaction_id TEXT NOT NULL,
                    worker_id TEXT, status TEXT NOT NULL, queue_ms REAL,
                    synthesis_ms REAL, first_audio_ms REAL, returned_ms REAL,
                    metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tts_requested ON tts_requests(requested_at);
                CREATE TABLE IF NOT EXISTS tts_queue_windows (
                    bucket_start TEXT NOT NULL, worker_id TEXT NOT NULL,
                    waiting_peak INTEGER NOT NULL, running_peak INTEGER NOT NULL,
                    oldest_wait_ms REAL NOT NULL, PRIMARY KEY(bucket_start, worker_id)
                );
            """)
            self._conn.execute("UPDATE tts_requests SET status='incomplete' WHERE status='pending'")
            self._conn.commit()

    def record_population(self, sampled_at, runtime_id, counts):
        self._execute(
            "INSERT OR REPLACE INTO stage_population_samples VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                sampled_at,
                runtime_id,
                *(
                    counts[key]
                    for key in (
                        "scope_count",
                        "chat_stage_count",
                        "call_stage_count",
                        "overlap_count",
                        "terminating_stage_count",
                    )
                ),
            ),
        )

    def record_tts_request(self, row):
        self.defer_metric_write(
            self._execute,
            "INSERT OR REPLACE INTO tts_requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            tuple(
                row[key]
                for key in (
                    "request_id",
                    "requested_at",
                    "user_id",
                    "character_id",
                    "interaction_id",
                    "worker_id",
                    "status",
                    "queue_ms",
                    "synthesis_ms",
                    "first_audio_ms",
                    "returned_ms",
                    "metadata_json",
                )
            ),
        )

    def record_tts_queue(self, bucket, worker, waiting, running, oldest):
        self.defer_metric_write(
            self._execute,
            """INSERT INTO tts_queue_windows VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(bucket_start, worker_id) DO UPDATE SET
                 waiting_peak=MAX(waiting_peak, excluded.waiting_peak),
                 running_peak=MAX(running_peak, excluded.running_peak),
                 oldest_wait_ms=MAX(oldest_wait_ms, excluded.oldest_wait_ms)""",
            (bucket, worker, waiting, running, oldest),
        )

    def usage_trends(self, window="24h", *, now=None):
        now = now or datetime.now(timezone.utc)
        since = window_start(window, now)
        if since is None:
            raise ValueError("usage trends require 24h or 7d")
        step = 300 if window == "24h" else 3600
        first = int(since.timestamp()) // step * step
        last = int(now.timestamp()) // step * step
        rows = {
            stamp: {
                "ts": datetime.fromtimestamp(stamp, timezone.utc).isoformat(),
                "online": None,
                "online_peak": None,
                "calls": 0,
                "tokens": 0,
            }
            for stamp in range(first, last + 1, step)
        }
        samples = defaultdict(list)
        populations = self._query_all(
            "SELECT * FROM stage_population_samples WHERE sampled_at >= ? AND sampled_at <= ? ORDER BY sampled_at",
            (since.isoformat(), now.isoformat()),
        )
        for sample in populations:
            bucket = int(datetime.fromisoformat(sample["sampled_at"]).timestamp()) // step * step
            samples[bucket].append(sample["scope_count"])
        for bucket, values in samples.items():
            rows[bucket].update(online=sum(values) / len(values), online_peak=max(values))
        calls = self._query_all(
            "SELECT ts, total_tokens FROM llm_call_metrics WHERE ts >= ? AND ts <= ?",
            (since.isoformat(), now.isoformat()),
        )
        for call in calls:
            bucket = int(datetime.fromisoformat(call["ts"]).timestamp()) // step * step
            rows[bucket]["calls"] += 1
            rows[bucket]["tokens"] += call["total_tokens"]
        return {
            "window": window,
            "bucket_seconds": step,
            "timezone": "Asia/Shanghai",
            "rows": list(rows.values()),
            "latest_population": populations[-1] if populations else None,
            "totals": {
                "calls": len(calls),
                "tokens": sum(row["total_tokens"] for row in calls),
                "online_peak": max((row["scope_count"] for row in populations), default=None),
            },
        }

    def latency_groups(self, window="24h", *, now=None):
        now = now or datetime.now(timezone.utc)
        since = window_start(window, now)
        spans = self._query_all(
            "SELECT * FROM pipeline_spans WHERE start_ts <= ?"
            + (" AND start_ts >= ?" if since else "")
            + " ORDER BY start_ts, id",
            (now.isoformat(), since.isoformat()) if since else (now.isoformat(),),
        )
        tts = self._query_all(
            "SELECT * FROM tts_requests WHERE requested_at <= ?" + (" AND requested_at >= ?" if since else ""),
            (now.isoformat(), since.isoformat()) if since else (now.isoformat(),),
        )
        groups = [self._span_group("chat", "聊天回复", CHAT, spans), self._span_group("call", "通话回复", CALL, spans)]
        groups.append(
            {
                "id": "tts",
                "title": "TTS",
                "outcomes": _outcomes(tts),
                "rows": [
                    self._latency_row(key, label, [row[key] for row in tts if row[key] is not None])
                    for key, label in (
                        ("first_audio_ms", "请求至首包产出"),
                        ("queue_ms", "排队等待"),
                        ("synthesis_ms", "开始合成至首包产出"),
                    )
                ],
            }
        )
        groups.extend(self._stage_group(kind, spans) for kind in ("chat", "call"))
        dates = [row["start_ts"] for row in spans] + [row["requested_at"] for row in tts]
        return {
            "window": window,
            "since": since.isoformat() if since else min(dates, default=None),
            "until": now.isoformat(),
            "groups": groups,
        }

    def _latency_row(self, key, label, values):
        summary = self._summarize_values(values)
        return {
            "key": key,
            "label": label,
            **{key: summary[key] for key in ("count", "avg_ms", "p50_ms", "p90_ms", "p99_ms")},
        }

    def _span_group(self, kind, title, phases, spans):
        selected = [row for row in spans if row["span_name"].startswith(f"{kind}.v2.")]
        return {
            "id": kind,
            "title": title,
            "outcomes": _outcomes([row for row in selected if row["span_name"] == f"{kind}.v2.terminal"]),
            "rows": [
                self._latency_row(key, label, _phase_values(selected, f"{kind}.v2.{key}")) for key, label in phases
            ],
        }

    def _stage_group(self, kind, spans):
        selected = [
            row
            for row in spans
            if row["span_name"].startswith("stage.termination.")
            and json.loads(row["metadata_json"] or "{}").get("stage_kind") == kind
        ]
        phases = (
            ("total", "完整回收"),
            ("stop_tasks", "停止任务"),
            ("maintenance", "认知维护"),
            ("close_context" if kind == "chat" else "cleanup", "资源清理"),
        )
        return {
            "id": f"stage_{kind}",
            "title": "聊天 Stage 回收" if kind == "chat" else "通话 Stage 回收",
            "outcomes": _outcomes([row for row in selected if row["span_name"] == "stage.termination.total"]),
            "rows": [
                self._latency_row(key, label, _phase_values(selected, f"stage.termination.{key}"))
                for key, label in phases
            ],
        }


def _phase_values(rows, name):
    grouped = defaultdict(list)
    for row in rows:
        if row["span_name"] == name:
            grouped[row["trace_id"]].append(row)
    return [
        sum(row["duration_ms"] for row in values)
        for values in grouped.values()
        if all(row["status"] == "success" for row in values)
    ]


def _outcomes(rows):
    result = defaultdict(int)
    for row in rows:
        result[row["status"]] += 1
    return dict(result)
