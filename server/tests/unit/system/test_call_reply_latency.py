from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.infrastructure.observability.call_metrics import CallMetrics
from src.infrastructure.observability.call_reply_timing import CallReplyTiming, mark_reply_phase, reply_timing_scope
from src.infrastructure.observability.service import ObservabilityService


def test_call_reply_endpoint_requires_admin_and_returns_empty_statistics(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.application.admin.auth import AdminAuthService
    from src.web.admin import admin_interface

    service = ObservabilityService({"db_path": str(tmp_path / "metrics.sqlite3")})
    auth = AdminAuthService(tmp_path / "auth.json", tmp_path / "setup-token")
    auth.setup((tmp_path / "setup-token").read_text(), "test-password-123")
    token = auth.login("test-password-123")["token"]
    monkeypatch.setattr(admin_interface, "get_admin_shell", lambda: SimpleNamespace(auth=auth, observability=service))
    app = FastAPI()
    app.include_router(admin_interface.router)
    try:
        with TestClient(app) as client:
            assert client.get("/admin/api/pipeline/call-replies").status_code == 401
            headers = {"Authorization": f"Bearer {token}"}
            response = client.get("/admin/api/pipeline/call-replies", headers=headers)
            assert response.status_code == 200
            assert response.json()["attempt_count"] == 0
            assert response.json()["summary"]["total"]["count"] == 0
            assert client.get("/admin/api/pipeline/call-replies?days=0", headers=headers).status_code == 422
    finally:
        service.close()


def test_reply_latency_summary_keeps_failed_and_missing_samples_out_of_success_statistics(tmp_path):
    service = ObservabilityService({"db_path": str(tmp_path / "metrics.sqlite3")})
    clock = [10.0]
    call_id = uuid4()

    def new(request_id, end):
        return CallReplyTiming(
            call_id=call_id,
            request_id=request_id,
            turn_seq=1,
            recognized_at=10.0,
            speech_ended_at=end,
            sink=CallMetrics(service).record_reply_span,
            clock=lambda: clock[0],
            wall_clock=lambda: datetime.now(timezone.utc),
        )

    try:
        timing = new("completed", 9.2)
        timing.record_retrieval_details(
            {
                "embedding": {"duration_ms": 50.0, "count": 1, "status": "success"},
                "vector_search": {"duration_ms": 10.0, "count": 2, "status": "success"},
            }
        )
        with reply_timing_scope(timing):
            for phase in (
                "retrieval_started",
                "retrieval_finished",
                "generation_started",
                "reply_generated",
                "reply_submitted",
                "tts_first_packet",
            ):
                clock[0] += 0.1
                mark_reply_phase(phase)
            mark_reply_phase("tts_first_packet")
        timing.finish("interrupted")
        failed = new("failed", None)
        with reply_timing_scope(failed):
            mark_reply_phase("retrieval_started")
            clock[0] += 0.5
            mark_reply_phase("retrieval_finished", status="error")
        failed.finish("failed")
        mark_reply_phase("tts_first_packet")  # 上下文已恢复，不得污染上一轮。
        result = service.get_call_reply_latency()
        assert result["attempt_count"] == 2
        assert result["completed_count"] == 1
        assert result["summary"]["total"]["count"] == 1
        assert result["summary"]["total"]["avg_ms"] == pytest.approx(1400)
        assert result["summary"]["retrieval.embedding"]["avg_ms"] == pytest.approx(50)
        assert result["summary"]["retrieval.vector_search"]["avg_ms"] == pytest.approx(10)
        assert result["summary"]["retrieval"]["count"] == 1
        assert result["summary"]["retrieval"]["failed_count"] == 1
        failure = next(a for a in result["recent"] if a["request_id"] == "failed")
        assert failure["outcome"] == "failed"
        assert "total" not in failure["phases"]
        assert failure["speech_end_basis"] == "unavailable"
    finally:
        service.close()
