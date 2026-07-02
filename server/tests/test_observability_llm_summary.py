import sys
from pathlib import Path

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.system.observability.service import ObservabilityService


def insert_llm_call(
    service: ObservabilityService,
    *,
    ts: str,
    module_name: str,
    total_tokens: int,
    latency_ms: float,
    success: int = 1,
) -> None:
    service._execute(
        """
        INSERT INTO llm_call_metrics (
            ts, trace_id, user_id, module_name, interface_name, model_name,
            prompt_tokens, completion_tokens, total_tokens, latency_ms,
            success, error_type, error_message, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts,
            None,
            None,
            module_name,
            "OpenAIAPIInterface",
            "qwen3.5-plus",
            total_tokens - 10,
            10,
            total_tokens,
            latency_ms,
            success,
            None,
            None,
            "{}",
        ),
    )


def test_llm_summary_days_has_module_and_time_buckets(tmp_path):
    service = ObservabilityService({"db_path": str(tmp_path / "metrics.sqlite3")})
    try:
        insert_llm_call(
            service,
            ts="2999-01-01T00:15:00.000+00:00",
            module_name="module_a",
            total_tokens=100,
            latency_ms=1000,
        )
        insert_llm_call(
            service,
            ts="2999-01-01T01:45:00.000+00:00",
            module_name="module_a",
            total_tokens=200,
            latency_ms=3000,
            success=0,
        )
        insert_llm_call(
            service,
            ts="2999-01-01T03:00:00.000+00:00",
            module_name="module_b",
            total_tokens=300,
            latency_ms=5000,
        )

        summary = service.get_llm_summary(days=90, bucket_hours=2)

        assert summary["window_type"] == "days"
        assert summary["totals"]["call_count"] == 3
        assert summary["totals"]["total_tokens"] == 600
        assert summary["totals"]["failed_calls"] == 1
        assert [row["module_name"] for row in summary["by_module"]] == ["module_a", "module_b"]
        assert len(summary["time_buckets"]) == 12
        assert summary["time_buckets"][0]["bucket_label"] == "00:00-02:00"
        assert summary["time_buckets"][-1]["bucket_label"] == "22:00-00:00"
        assert sum(row["call_count"] for row in summary["time_buckets"]) == 3
        assert sorted(row["call_count"] for row in summary["time_buckets"] if row["call_count"]) == [1, 2]
    finally:
        service.close()


def test_llm_summary_recent_limit_uses_latest_calls(tmp_path):
    service = ObservabilityService({"db_path": str(tmp_path / "metrics.sqlite3")})
    try:
        for idx in range(5):
            insert_llm_call(
                service,
                ts=f"2999-01-01T00:0{idx}:00.000+00:00",
                module_name="module_a" if idx % 2 == 0 else "module_b",
                total_tokens=100 + idx,
                latency_ms=1000 + idx,
            )

        summary = service.get_llm_summary(recent_limit=2)

        assert summary["window_type"] == "recent"
        assert summary["recent_limit"] == 2
        assert summary["totals"]["call_count"] == 2
        assert summary["totals"]["total_tokens"] == 207
        assert summary["time_buckets"] == []
    finally:
        service.close()
