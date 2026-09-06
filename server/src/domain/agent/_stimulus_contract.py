from __future__ import annotations

from abc import ABCMeta
from datetime import datetime
from inspect import Signature, signature
from typing import Literal, NoReturn


StimulusErrorCode = Literal[
    "CONTRACT_INVALID_STIMULUS",
    "CONTRACT_UNSUPPORTED_SCHEMA",
    "CONTRACT_STIMULUS_UNAVAILABLE",
]
"""刺激构造失败码：字段非法、结构版本不受支持或登记类型不可构造。"""


class InvalidStimulusError(ValueError):
    """刺激或其值对象构造失败；code 标识原因，retryable 固定为 False。"""

    def __init__(self, message: str, *, code: StimulusErrorCode) -> None:
        super().__init__(message)
        self.code = code
        self.retryable: Literal[False] = False


def _public_constructor_signature(cls: type) -> Signature:
    parameters = tuple(signature(cls.__init__).parameters.values())[1:]
    return Signature(parameters=parameters)


class _ContractValueMeta(type):
    @property
    def __signature__(cls) -> Signature:
        return _public_constructor_signature(cls)

    def __call__(cls, *args: object, **kwargs: object):
        try:
            return super().__call__(*args, **kwargs)
        except InvalidStimulusError:
            raise
        except TypeError as error:
            raise InvalidStimulusError(
                "Invalid value-object fields",
                code="CONTRACT_INVALID_STIMULUS",
            ) from error


class _StimulusMeta(ABCMeta):
    @property
    def __signature__(cls) -> Signature:
        return _public_constructor_signature(cls)

    def __call__(cls, *args: object, **kwargs: object):
        if not cls._constructible:
            raise InvalidStimulusError(
                "This Stimulus type is registered but unavailable",
                code="CONTRACT_STIMULUS_UNAVAILABLE",
            )
        if cls.__abstractmethods__:
            return super().__call__(*args, **kwargs)
        try:
            return super().__call__(*args, **kwargs)
        except InvalidStimulusError:
            raise
        except TypeError as error:
            raise InvalidStimulusError(
                "Invalid or missing Stimulus fields",
                code="CONTRACT_INVALID_STIMULUS",
            ) from error


def _is_nonblank_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _require_nonblank_string(value: object) -> None:
    if not _is_nonblank_string(value):
        _raise_invalid()


def _require_optional_nonblank_string(value: object) -> None:
    if value is not None:
        _require_nonblank_string(value)


def _require_nonnegative_int(value: object) -> None:
    if type(value) is not int or value < 0:
        _raise_invalid()


def _require_aware_datetime(value: object) -> None:
    if not isinstance(value, datetime):
        _raise_invalid()
    try:
        aware = value.tzinfo is not None and value.utcoffset() is not None
    except (OverflowError, TypeError, ValueError):
        aware = False
    if not aware:
        _raise_invalid()


def _require_instance(value: object, expected_type: type) -> None:
    if not isinstance(value, expected_type):
        _raise_invalid()


def _require_optional_instance(value: object, expected_type: type) -> None:
    if value is not None:
        _require_instance(value, expected_type)


def _require_tuple_of(
    value: object,
    member_type: type,
    *,
    allow_empty: bool = True,
) -> None:
    if type(value) is not tuple:
        _raise_invalid()
    if not allow_empty and not value:
        _raise_invalid()
    if any(not isinstance(member, member_type) for member in value):
        _raise_invalid()


def _require_string_tuple(value: object, *, allow_empty: bool = True) -> None:
    if type(value) is not tuple:
        _raise_invalid()
    if not allow_empty and not value:
        _raise_invalid()
    if any(not _is_nonblank_string(member) for member in value):
        _raise_invalid()


def _raise_invalid() -> NoReturn:
    raise InvalidStimulusError(
        "Invalid Stimulus contract field",
        code="CONTRACT_INVALID_STIMULUS",
    )
