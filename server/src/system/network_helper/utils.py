from fastapi import HTTPException
from src.system.admin.admin_shell import get_admin_shell

def require_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="消息令牌缺失")
    scheme, separator, token = authorization.partition(" ")
    if (
        separator != " "
        or scheme.lower() != "bearer"
        or not token
        or any(character.isspace() for character in token)
    ):
        raise HTTPException(status_code=401, detail="无效的 Authorization 请求头")
    return token

def runtime_not_ready_detail() -> dict:
    status = get_admin_shell().runtime_supervisor.public_status()
    return {
        "ok": False,
        "code": "SYSTEM_RUNTIME_NOT_READY",
        "message": "服务端尚未完成配置或系统运行时未启动",
        "runtime": status,
    }