"""统一的 HTTP 错误响应：在 `detail` 之外平铺稳定错误码，供客户端流程分支使用。"""

from typing import Optional

from fastapi.responses import JSONResponse


def agreement_error_response(
    status_code: int, detail: str, *, code: Optional[str] = None, **extra: object
) -> JSONResponse:
    """错误体统一为 `{"detail": ..., "code": ...}`；其余字段（如当前协议版本）平铺在顶层。

    不带 `code` 时（例如邀请码或用户名不可用）保持与既有响应完全一致，只有 `detail`。
    """
    body: dict[str, object] = {"detail": detail}
    if code:
        body["code"] = code
    body.update(extra)
    return JSONResponse(status_code=status_code, content=body)
