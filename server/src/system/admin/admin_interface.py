from __future__ import annotations

import asyncio
import copy
import json
from datetime import datetime
from typing import Any, Optional, TYPE_CHECKING

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse

from .admin_shell import get_admin_shell
from .llm_config_editor import apply_llm_config_draft, build_llm_config_view
from .system_dynamic_publisher import publish_system_dynamic
from src.system.user_interface.rate_limits import enforce_rate_limit
from src.utils.helpers import apply_env_variables

if TYPE_CHECKING:
    from src.system.system_runtime import SystemRuntime

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


REQUIRED_SECRET_KEYS = ["JWT_SECRET", "AMAP_KEY"]


def _extract_env_name(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw.startswith("$"):
        return None
    name = raw[1:]
    if name.startswith("{") and name.endswith("}"):
        name = name[1:-1]
    return name.strip() or None


def _collect_llm_api_key_names(config: dict[str, Any]) -> set[str]:
    llm_service = config.get("llm_service", {}) or {}
    names: set[str] = set()
    for collection_name in ("available_llms", "available_vlms"):
        collection = llm_service.get(collection_name, {}) or {}
        for item in collection.values():
            if not isinstance(item, dict):
                continue
            env_name = _extract_env_name(item.get("api_key"))
            if env_name:
                names.add(env_name)
    return names


def _ordered_secret_names(required: list[str], referenced: set[str], stored: set[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for name in required:
        result.append(name)
        seen.add(name)
    for name in sorted(referenced):
        if name not in seen:
            result.append(name)
            seen.add(name)
    for name in sorted(stored):
        if name not in seen:
            result.append(name)
            seen.add(name)
    return result


def _parse_admin_datetime_filter(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    normalized = raw.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(normalized, fmt)
            if fmt == "%Y-%m-%d" and end_of_day:
                return parsed.replace(hour=23, minute=59, second=59)
            return parsed
        except ValueError:
            continue
    raise HTTPException(status_code=400, detail=f"无效的时间格式: {raw}")


def _parse_bool_payload(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off", ""}:
        return False
    return default


def _parse_invite_code_payload(payload: dict[str, Any]) -> str:
    value = payload.get("code")
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail="邀请码不能为空")
    code = value.strip()
    if not code or len(code) > 256:
        raise HTTPException(status_code=400, detail="邀请码格式无效")
    return code


router = APIRouter(prefix="/admin/api", tags=["admin"])
protected_router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/health")
async def admin_health() -> dict[str, Any]:
    shell = get_admin_shell()
    return {
        "status": "ok",
        "admin_auth": shell.auth.status(),
        "runtime": shell.runtime_supervisor.public_status(),
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
    request: Request,
    response: Response,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    password = str(payload.get("password") or "")
    enforce_rate_limit(request, "admin_login", "admin")
    return await get_admin_shell().auth.login_async(password, response)


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
    shell = get_admin_shell()
    try:
        config = shell.config_store.read_raw()
    except (json.JSONDecodeError, OSError):
        config = {}
    referenced_llm_keys = _collect_llm_api_key_names(config)
    stored_keys = set(shell.secret_store.read().keys())
    keys = _ordered_secret_names(REQUIRED_SECRET_KEYS, referenced_llm_keys, stored_keys)
    status = shell.secret_store.status(keys)
    for key, item in status.items():
        item["required"] = key in REQUIRED_SECRET_KEYS
        item["referenced"] = key in referenced_llm_keys
        item["category"] = "required" if key in REQUIRED_SECRET_KEYS else "llm_api_key" if key in referenced_llm_keys else "custom"
    return status


@protected_router.put("/secrets")
async def update_secrets(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    shell = get_admin_shell()
    before = shell.secret_store.read()
    after = shell.secret_store.update(payload)
    changed_keys = sorted(
        key
        for key in before.keys() | after.keys()
        if before.get(key) != after.get(key)
    )
    return {
        "ok": True,
        "secrets": await secrets_status(),
        "restart_required": bool(changed_keys and shell.runtime_supervisor.is_running()),
        "changed_keys": changed_keys,
    }


@protected_router.get("/qq-music/credential/status")
async def qq_music_credential_status() -> dict[str, Any]:
    return get_admin_shell().qq_music_credential_refresh.status()


@protected_router.post("/qq-music/credential/refresh")
async def refresh_qq_music_credential() -> dict[str, Any]:
    return get_admin_shell().qq_music_credential_refresh.start(timeout_seconds=30)


@protected_router.get("/qq-music/credential/qr")
async def qq_music_credential_qr() -> FileResponse:
    qr_file = get_admin_shell().qq_music_credential_refresh.qr_file()
    if qr_file is None or not qr_file.is_file():
        raise HTTPException(status_code=404, detail="QQ 音乐登录二维码尚未生成")
    return FileResponse(qr_file, media_type="image/png")


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


@protected_router.get("/calls")
async def calls(
    limit: int = Query(default=100, ge=1, le=1000),
    user_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    runtime: "SystemRuntime" | None = get_admin_shell().runtime_supervisor.runtime
    if runtime is None or runtime.database_manager.call_store is None:
        raise HTTPException(status_code=503, detail="system runtime is not running")
    return await asyncio.to_thread(
        runtime.database_manager.call_store.list_sessions,
        limit=limit,
        user_id=user_id,
        status=status,
    )


@protected_router.get("/calls/{call_id}")
async def call_summary(call_id: str) -> dict[str, Any]:
    runtime: "SystemRuntime" | None = get_admin_shell().runtime_supervisor.runtime
    if runtime is None or runtime.database_manager.call_store is None:
        raise HTTPException(status_code=503, detail="system runtime is not running")
    result = await asyncio.to_thread(
        runtime.database_manager.call_store.get_session_summary,
        call_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="call not found")
    return result


@protected_router.get("/calls-events")
async def call_events(
    limit: int = Query(default=100, ge=1, le=1000),
    call_id: str | None = None,
    event_name: str | None = None,
) -> list[dict[str, Any]]:
    return get_admin_shell().observability.get_recent_call_events(
        limit=limit,
        call_id=call_id,
        event_name=event_name,
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


@protected_router.get("/dynamics")
async def admin_dynamics(
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = None,
    owner_user_id: str | None = None,
    author_type: str | None = None,
    source_type: str | None = None,
    status: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
) -> dict[str, Any]:
    runtime: "SystemRuntime" | None = get_admin_shell().runtime_supervisor.runtime
    if runtime is None:
        raise HTTPException(status_code=503, detail="system runtime is not running")
    return runtime.database_manager.dynamic_store.admin_list_dynamics(
        limit=limit,
        cursor=cursor,
        owner_user_id=owner_user_id,
        author_type=author_type,
        source_type=source_type,
        status=status,
        created_after=_parse_admin_datetime_filter(created_after),
        created_before=_parse_admin_datetime_filter(created_before, end_of_day=True),
    )


@protected_router.post("/dynamics/system")
async def admin_create_system_dynamic(
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    runtime: "SystemRuntime" | None = get_admin_shell().runtime_supervisor.runtime
    if runtime is None:
        raise HTTPException(status_code=503, detail="system runtime is not running")

    content = str(payload.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="系统动态内容不能为空")

    visibility = str(payload.get("visibility") or "global").strip()
    if visibility != "global":
        raise HTTPException(status_code=400, detail="系统动态目前只支持全局可见")

    source_type = str(payload.get("source_type") or "system_notice").strip() or "system_notice"
    source_id = str(payload.get("source_id") or "").strip() or None
    allow_comment = _parse_bool_payload(payload.get("allow_comment"), default=False)
    ok, message, item = publish_system_dynamic(
        runtime.database_manager,
        content=content,
        source_type=source_type,
        source_id=source_id,
        visibility=visibility,
        allow_comment=allow_comment,
    )
    if not ok or item is None:
        raise HTTPException(status_code=400, detail=message)
    return {"ok": True, "item": item}


@protected_router.get("/dynamics/{dynamic_id}/comments")
async def admin_dynamic_comments(
    dynamic_id: str,
    limit: int = Query(default=200, ge=1, le=500),
    owner_user_id: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
) -> dict[str, Any]:
    runtime: "SystemRuntime" | None = get_admin_shell().runtime_supervisor.runtime
    if runtime is None:
        raise HTTPException(status_code=503, detail="system runtime is not running")
    return runtime.database_manager.dynamic_store.admin_list_dynamic_comments(
        dynamic_id,
        limit=limit,
        owner_user_id=owner_user_id,
        created_after=_parse_admin_datetime_filter(created_after),
        created_before=_parse_admin_datetime_filter(created_before, end_of_day=True),
    )


# ── 邀请码管理 ────────────────────────────────────────────────

@protected_router.post("/invite-codes/query")
async def admin_list_invite_codes(
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    runtime: "SystemRuntime" | None = get_admin_shell().runtime_supervisor.runtime
    if runtime is None:
        raise HTTPException(status_code=503, detail="system runtime is not running")

    try:
        limit = int(payload.get("limit", 100))
        offset = int(payload.get("offset", 0))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="分页参数无效") from exc
    if limit < 1 or limit > 500 or offset < 0:
        raise HTTPException(status_code=400, detail="分页参数无效")

    status = str(payload.get("status") or "").strip() or None
    if status not in {None, "unused", "used", "disabled"}:
        raise HTTPException(status_code=400, detail="邀请码状态无效")
    search = str(payload.get("search") or "").strip() or None
    if search is not None and len(search) > 128:
        raise HTTPException(status_code=400, detail="搜索内容过长")
    return runtime.database_manager.admin_list_invite_codes(
        limit=limit,
        offset=offset,
        status=status,
        search=search,
    )


@protected_router.post("/invite-codes/generate")
async def admin_generate_invite_codes(
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    runtime: "SystemRuntime" | None = get_admin_shell().runtime_supervisor.runtime
    if runtime is None:
        raise HTTPException(status_code=503, detail="system runtime is not running")
    raw_count = payload.get("count", 1)
    if isinstance(raw_count, bool):
        raise HTTPException(status_code=400, detail="生成数量需在 1-100 之间")
    try:
        count = int(raw_count)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="生成数量需在 1-100 之间") from exc
    ok, result = runtime.database_manager.admin_generate_invite_codes(count=count)
    if not ok:
        raise HTTPException(status_code=400, detail=result)
    return {"ok": True, "codes": result}


@protected_router.post("/invite-codes/disable")
async def admin_disable_invite_code(
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    runtime: "SystemRuntime" | None = get_admin_shell().runtime_supervisor.runtime
    if runtime is None:
        raise HTTPException(status_code=503, detail="system runtime is not running")
    ok, message = runtime.database_manager.admin_disable_invite_code(
        _parse_invite_code_payload(payload)
    )
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"ok": True, "message": message}


@protected_router.post("/invite-codes/delete")
async def admin_delete_invite_code(
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    runtime: "SystemRuntime" | None = get_admin_shell().runtime_supervisor.runtime
    if runtime is None:
        raise HTTPException(status_code=503, detail="system runtime is not running")
    ok, message = runtime.database_manager.admin_delete_invite_code(
        _parse_invite_code_payload(payload)
    )
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"ok": True, "message": message}


router.include_router(protected_router)
