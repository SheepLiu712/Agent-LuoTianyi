from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query

from src.system.system_runtime import SystemRuntime, get_system_runtime


def get_runtime() -> SystemRuntime:
    return get_system_runtime()


router = APIRouter(prefix="/admin/api", tags=["admin"])


@router.get("/health")
async def admin_health(system_runtime: SystemRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return {
        "status": "ok",
        "observability": system_runtime.observability is not None,
    }


@router.get("/dashboard")
async def dashboard(
    days: int = Query(default=1, ge=1, le=90),
    system_runtime: SystemRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return system_runtime.observability.get_dashboard_summary(days=days)


@router.get("/llm/summary")
async def llm_summary(
    days: int = Query(default=7, ge=1, le=90),
    system_runtime: SystemRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return system_runtime.observability.get_llm_summary(days=days)


@router.get("/llm/calls")
async def llm_calls(
    limit: int = Query(default=100, ge=1, le=1000),
    module_name: str | None = None,
    trace_id: str | None = None,
    system_runtime: SystemRuntime = Depends(get_runtime),
) -> list[dict[str, Any]]:
    return system_runtime.observability.get_recent_llm_calls(
        limit=limit,
        module_name=module_name,
        trace_id=trace_id,
    )


@router.get("/pipeline/latency")
async def pipeline_latency(
    days: int = Query(default=7, ge=1, le=90),
    system_runtime: SystemRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return system_runtime.observability.get_pipeline_latency_summary(days=days)


@router.get("/pipeline/spans")
async def pipeline_spans(
    limit: int = Query(default=100, ge=1, le=1000),
    trace_id: str | None = None,
    slow: bool = False,
    system_runtime: SystemRuntime = Depends(get_runtime),
) -> list[dict[str, Any]]:
    return system_runtime.observability.get_recent_pipeline_spans(
        limit=limit,
        trace_id=trace_id,
        order_by_slow=slow,
    )


@router.get("/traces")
async def traces(
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=100, ge=1, le=1000),
    system_runtime: SystemRuntime = Depends(get_runtime),
) -> list[dict[str, Any]]:
    return system_runtime.observability.get_trace_summaries(days=days, limit=limit)


@router.get("/traces/{trace_id}")
async def trace_detail(
    trace_id: str,
    system_runtime: SystemRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return system_runtime.observability.get_trace_detail(trace_id)


@router.get("/memory/summary")
async def memory_summary(
    days: int = Query(default=7, ge=1, le=90),
    system_runtime: SystemRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return system_runtime.observability.get_memory_trace_summary(days=days)


@router.get("/memory/events")
async def memory_events(
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=200, ge=1, le=1000),
    trace_id: str | None = None,
    event_type: str | None = None,
    annotation_state: str | None = None,
    system_runtime: SystemRuntime = Depends(get_runtime),
) -> list[dict[str, Any]]:
    return system_runtime.observability.get_memory_trace_events(
        days=days,
        limit=limit,
        trace_id=trace_id,
        event_type=event_type,
        annotation_state=annotation_state,
    )


@router.post("/memory/events/{event_id}/annotation")
async def annotate_memory_event(
    event_id: int,
    payload: dict[str, Any] = Body(default_factory=dict),
    system_runtime: SystemRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return system_runtime.observability.annotate_memory_trace_event(
        event_id,
        label=str(payload.get("label") or "").strip(),
        notes=str(payload.get("notes") or "").strip() or None,
        annotator=str(payload.get("annotator") or "").strip() or None,
    )


@router.get("/logs")
async def logs(
    limit: int = Query(default=100, ge=1, le=1000),
    min_level: str | None = "WARNING",
    system_runtime: SystemRuntime = Depends(get_runtime),
) -> list[dict[str, Any]]:
    return system_runtime.observability.get_recent_logs(limit=limit, min_level=min_level)
