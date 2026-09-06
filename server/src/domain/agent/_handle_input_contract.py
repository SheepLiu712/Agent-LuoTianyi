"""Construction errors and argument validation shared by handle input values."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from functools import wraps
from inspect import Signature, signature


class HandleInputErrorCode(str, Enum):
    """handle 输入的稳定错误码，分别标识快照、请求和取消令牌契约错误。"""

    CONTRACT_INVALID_INTERACTION = "CONTRACT_INVALID_INTERACTION"
    CONTRACT_INVALID_HANDLE_REQUEST = "CONTRACT_INVALID_HANDLE_REQUEST"
    CONTRACT_INVALID_CANCELLATION = "CONTRACT_INVALID_CANCELLATION"


class InvalidHandleInputError(ValueError):
    """handle 输入校验失败，通过只读 code 属性提供稳定错误码。"""

    def __init__(self, message: str, *, code: HandleInputErrorCode) -> None:
        super().__init__(message)
        self._code = code

    @property
    def code(self) -> HandleInputErrorCode:
        """返回快照、请求或取消令牌校验失败的分类。"""
        return self._code


def _bind(signature_: Signature, code: HandleInputErrorCode, *args, **kwargs) -> None:
    try:
        signature_.bind(*args, **kwargs)
    except TypeError as error:
        raise InvalidHandleInputError("Invalid or missing input arguments", code=code) from error


class _HandleInputMeta(type):
    @property
    def __signature__(cls) -> Signature:
        return signature(cls.__init__).replace(
            parameters=tuple(signature(cls.__init__).parameters.values())[1:],
        )

    def __call__(cls, *args, **kwargs):
        _bind(signature(cls), cls._error_code, *args, **kwargs)
        return super().__call__(*args, **kwargs)


def _checked_arguments(code: HandleInputErrorCode):
    """Normalize argument-binding failures without swallowing implementation errors."""
    def decorate(method):
        method_signature = signature(method)

        @wraps(method)
        def checked(*args, **kwargs):
            _bind(method_signature, code, *args, **kwargs)
            return method(*args, **kwargs)

        return checked

    return decorate


def _require(
    condition: bool,
    field: str,
    code: HandleInputErrorCode = HandleInputErrorCode.CONTRACT_INVALID_INTERACTION,
) -> None:
    if not condition:
        raise InvalidHandleInputError(f"Invalid {field}", code=code)


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _revision(value: object) -> bool:
    return type(value) is int and value >= 0


def _aware(value: object) -> bool:
    if not isinstance(value, datetime):
        return False
    try:
        return value.tzinfo is not None and value.utcoffset() is not None
    except (OverflowError, TypeError, ValueError):
        return False
