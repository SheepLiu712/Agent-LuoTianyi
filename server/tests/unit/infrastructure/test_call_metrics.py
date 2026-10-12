from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.infrastructure.observability import (
    CallCostStatus,
    CallMetric,
    CallMetricName,
    CallMetricResult,
    CallMetrics,
    ObservabilityService,
)


def test_call_metrics_store_only_allowlisted_content_free_fields(tmp_path):
    service = ObservabilityService({"db_path": str(tmp_path / "metrics.sqlite")})
    call_id = uuid4()
    timestamp = datetime.now(timezone.utc).isoformat()
    CallMetrics(service).record(
        CallMetric(
            call_id=call_id,
            name=CallMetricName.SUMMARY,
            start_ts=timestamp,
            end_ts=timestamp,
            duration_ms=0,
            numeric={"latency_ms": 12.5, "cost_microunits": None},
            labels={
                "result": CallMetricResult.FAILED.value,
                "error_code": "SUMMARY_UNAVAILABLE",
                "cost_status": CallCostStatus.UNKNOWN.value,
            },
        )
    )
    row = service.get_recent_pipeline_spans(limit=1)[0]
    assert row["trace_id"] == f"call:{call_id}"
    assert row["metadata"] == {
        "latency_ms": 12.5,
        "cost_microunits": None,
        "result": "failed",
        "error_code": "SUMMARY_UNAVAILABLE",
        "cost_status": "unknown",
    }
    service.close()


@pytest.mark.parametrize("field", ["transcript", "summary", "context", "pcm", "provider_exception"])
def test_call_metrics_reject_content_fields(field):
    timestamp = datetime.now(timezone.utc).isoformat()
    with pytest.raises(ValueError, match="unsupported"):
        CallMetric(
            call_id=uuid4(),
            name=CallMetricName.SUMMARY,
            start_ts=timestamp,
            end_ts=timestamp,
            duration_ms=0,
            labels={field: "secret"},
        )


@pytest.mark.parametrize("value", [True, -1, float("nan"), float("inf")])
def test_call_metrics_reject_invalid_numeric_values(value):
    timestamp = datetime.now(timezone.utc).isoformat()
    with pytest.raises(ValueError):
        CallMetric(
            call_id=uuid4(),
            name=CallMetricName.BUFFER,
            start_ts=timestamp,
            end_ts=timestamp,
            duration_ms=0,
            numeric={"buffered_bytes": value},
        )


@pytest.mark.parametrize("labels", [{"provider": "用户文本"}, {"error_code": "raw error message"}])
def test_call_metrics_reject_unregistered_or_raw_labels(labels):
    timestamp = datetime.now(timezone.utc).isoformat()
    with pytest.raises(ValueError):
        CallMetric(
            call_id=uuid4(),
            name=CallMetricName.PROVIDER_ENDPOINT,
            start_ts=timestamp,
            end_ts=timestamp,
            duration_ms=0,
            labels=labels,
        )


def test_call_metrics_sink_failure_is_best_effort_and_omits_exception_message(capture_project_log):
    class Sink:
        def record_pipeline_span(self, **values):
            raise RuntimeError("secret provider payload")

    capture_project_log("src.infrastructure.observability.call_metrics")
    timestamp = datetime.now(timezone.utc).isoformat()
    metric = CallMetric(
        call_id=uuid4(),
        name=CallMetricName.SUMMARY,
        start_ts=timestamp,
        end_ts=timestamp,
        duration_ms=0,
    )
    assert CallMetrics(Sink()).record(metric) is False
