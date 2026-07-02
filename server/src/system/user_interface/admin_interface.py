from __future__ import annotations

import copy
import json
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response

from src.system.admin import get_admin_shell
from src.system.admin.llm_config_editor import apply_llm_config_draft, build_llm_config_view
from src.utils.helpers import apply_env_variables


def require_admin(request: Request) -> None:
    get_admin_shell().auth.require_admin(request)


def config_read_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, json.JSONDecodeError):
        detail = {
            "code": "CONFIG_JSON_INVALID",
            "message": f"config.json 不是合法 JSON: line {exc.lineno} column {exc.colno}: {exc.msg}",
        }
    else:
        detail = {"code": "CONFIG_READ_FAILED", "message": f"config.json 读取失败: {exc}"}
    return HTTPException(status_code=400, detail=detail)


router = APIRouter(prefix="/admin/api", tags=["admin"])
protected_router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/health")
async def admin_health() -> dict[str, Any]:
    shell = get_admin_shell()
    return {
        "status": "ok",
        "admin_auth": shell.auth.status(),
        "runtime": shell.runtime_supervisor.status(),
        "observability": shell.observability is not None,
    }


@router.get("/admin-auth/status")
async def admin_auth_status() -> dict[str, Any]:
    return get_admin_shell().auth.status()


@router.post("/admin-auth/setup")
async def admin_auth_setup(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return get_admin_shell().auth.setup(
        setup_token=str(payload.get("setup_token") or ""),
        password=str(payload.get("password") or ""),
    )


@router.post("/admin-auth/login")
async def admin_auth_login(
    response: Response,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return get_admin_shell().auth.login(str(payload.get("password") or ""), response)


@protected_router.post("/admin-auth/logout")
async def admin_auth_logout(request: Request, response: Response) -> dict[str, Any]:
    return get_admin_shell().auth.logout(request, response)


@protected_router.get("/runtime/status")
async def runtime_status() -> dict[str, Any]:
    return get_admin_shell().runtime_supervisor.status()


@protected_router.post("/runtime/start")
async def runtime_start() -> dict[str, Any]:
    return get_admin_shell().runtime_supervisor.request_start()


@protected_router.post("/runtime/stop")
async def runtime_stop() -> dict[str, Any]:
    return get_admin_shell().runtime_supervisor.request_stop()


@protected_router.post("/runtime/restart")
async def runtime_restart() -> dict[str, Any]:
    return get_admin_shell().runtime_supervisor.request_restart()


@protected_router.get("/config")
async def read_config() -> dict[str, Any]:
    try:
        return get_admin_shell().config_store.read_raw()
    except (json.JSONDecodeError, OSError) as exc:
        raise config_read_http_error(exc) from exc


@protected_router.put("/config")
async def write_config(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    get_admin_shell().config_store.write_raw(payload)
    validation = get_admin_shell().runtime_supervisor.validate_current_config()
    return {"ok": True, "validation": validation}


@protected_router.get("/config/validation")
async def validate_config() -> dict[str, Any]:
    return get_admin_shell().runtime_supervisor.validate_current_config()


@protected_router.get("/secrets/status")
async def secrets_status() -> dict[str, Any]:
    keys = [
        "JWT_SECRET",
        "QWEN_API_KEY",
        "SILICONFLOW_API_KEY",
        "DEEPSEEK_API_KEY",
        "AMAP_KEY",
    ]
    return get_admin_shell().secret_store.status(keys)


@protected_router.put("/secrets")
async def update_secrets(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    get_admin_shell().secret_store.update(payload)
    return {"ok": True, "secrets": await secrets_status()}


@protected_router.get("/llm/config")
async def llm_config() -> dict[str, Any]:
    try:
        config = get_admin_shell().config_store.read_raw()
    except (json.JSONDecodeError, OSError) as exc:
        raise config_read_http_error(exc) from exc
    return build_llm_config_view(config)


@protected_router.post("/llm/config/apply")
async def apply_llm_config(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    shell = get_admin_shell()
    try:
        raw_config = shell.config_store.read_raw()
    except (json.JSONDecodeError, OSError) as exc:
        raise config_read_http_error(exc) from exc
    next_raw_config = apply_llm_config_draft(raw_config, payload)
    shell.secret_store.load_into_environment()
    validation = shell.validator.validate(apply_env_variables(copy.deepcopy(next_raw_config)))
    if not validation.get("core_ok"):
        return {
            "ok": False,
            "written": False,
            "restarted": False,
            "validation": validation,
            "runtime": shell.runtime_supervisor.status(),
        }

    was_running = shell.runtime_supervisor.is_running()
    shell.config_store.write_raw(next_raw_config)
    if was_running:
        runtime_status = await shell.runtime_supervisor.restart()
    else:
        shell.runtime_supervisor.validate_current_config()
        runtime_status = shell.runtime_supervisor.status()
    return {
        "ok": True,
        "written": True,
        "restarted": was_running,
        "validation": shell.runtime_supervisor.last_validation or validation,
        "runtime": runtime_status,
    }


@protected_router.get("/dashboard")
async def dashboard(
    days: int = Query(default=1, ge=1, le=90),
) -> dict[str, Any]:
    return get_admin_shell().observability.get_dashboard_summary(days=days)


@protected_router.get("/llm/summary")
async def llm_summary(
    days: int = Query(default=7, ge=1, le=90),
    recent_limit: Optional[int] = Query(default=None, ge=1, le=1000),
    bucket_hours: int = Query(default=2, ge=1, le=24),
) -> dict[str, Any]:
    return get_admin_shell().observability.get_llm_summary(
        days=days,
        recent_limit=recent_limit,
        bucket_hours=bucket_hours,
    )


@protected_router.get("/llm/calls")
async def llm_calls(
    limit: int = Query(default=100, ge=1, le=1000),
    module_name: str | None = None,
    trace_id: str | None = None,
) -> list[dict[str, Any]]:
    return get_admin_shell().observability.get_recent_llm_calls(
        limit=limit,
        module_name=module_name,
        trace_id=trace_id,
    )


@protected_router.get("/pipeline/latency")
async def pipeline_latency(
    days: int = Query(default=7, ge=1, le=90),
) -> dict[str, Any]:
    return get_admin_shell().observability.get_pipeline_latency_summary(days=days)


@protected_router.get("/pipeline/spans")
async def pipeline_spans(
    limit: int = Query(default=100, ge=1, le=1000),
    trace_id: str | None = None,
    slow: bool = False,
) -> list[dict[str, Any]]:
    return get_admin_shell().observability.get_recent_pipeline_spans(
        limit=limit,
        trace_id=trace_id,
        order_by_slow=slow,
    )


@protected_router.get("/traces")
async def traces(
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[dict[str, Any]]:
    return get_admin_shell().observability.get_trace_summaries(days=days, limit=limit)


@protected_router.get("/traces/{trace_id}")
async def trace_detail(
    trace_id: str,
) -> dict[str, Any]:
    return get_admin_shell().observability.get_trace_detail(trace_id)


@protected_router.get("/memory/summary")
async def memory_summary(
    days: int = Query(default=7, ge=1, le=90),
) -> dict[str, Any]:
    return get_admin_shell().observability.get_memory_trace_summary(days=days)


@protected_router.get("/memory/events")
async def memory_events(
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=200, ge=1, le=1000),
    trace_id: str | None = None,
    event_type: str | None = None,
    annotation_state: str | None = None,
) -> list[dict[str, Any]]:
    return get_admin_shell().observability.get_memory_trace_events(
        days=days,
        limit=limit,
        trace_id=trace_id,
        event_type=event_type,
        annotation_state=annotation_state,
    )


@protected_router.post("/memory/events/{event_id}/annotation")
async def annotate_memory_event(
    event_id: int,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return get_admin_shell().observability.annotate_memory_trace_event(
        event_id,
        label=str(payload.get("label") or "").strip(),
        notes=str(payload.get("notes") or "").strip() or None,
        annotator=str(payload.get("annotator") or "").strip() or None,
    )


@protected_router.get("/logs")
async def logs(
    limit: int = Query(default=100, ge=1, le=1000),
    min_level: str | None = "WARNING",
) -> list[dict[str, Any]]:
    return get_admin_shell().observability.get_recent_logs(limit=limit, min_level=min_level)


router.include_router(protected_router)
