import asyncio

import pytest

from src.infrastructure.observability import ObservabilityService, stage_timing


def test_timing_storage_failure_does_not_mask_business_result(monkeypatch):
    class BrokenStore:
        def record_pipeline_span(self, **values):
            raise RuntimeError("metrics unavailable")

    monkeypatch.setattr(stage_timing, "get_observability_service", lambda: BrokenStore())
    with stage_timing.stage_timing("interaction", "stage.termination.total"):
        pass
    with pytest.raises(ValueError, match="business failure"):
        with stage_timing.stage_timing("interaction", "stage.termination.total"):
            raise ValueError("business failure")


def test_timing_records_cancellation_without_message_content(tmp_path, monkeypatch):
    service = ObservabilityService({"db_path": str(tmp_path / "metrics.sqlite3")})
    monkeypatch.setattr(stage_timing, "get_observability_service", lambda: service)
    try:
        with pytest.raises(asyncio.CancelledError):
            with stage_timing.stage_timing("interaction", "stage.termination.total"):
                raise asyncio.CancelledError("private content")
        rows = service.get_recent_pipeline_spans(trace_id="stage:interaction")
        assert len(rows) == 1 and rows[0]["status"] == "cancelled"
        assert "private content" not in str(rows)
    finally:
        service.close()
