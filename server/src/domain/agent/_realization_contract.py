"""realization 值对象的字段校验与构造错误。"""
from abc import ABCMeta
from dataclasses import fields
from datetime import date
from enum import Enum
from inspect import isabstract, signature
from types import UnionType
from typing import get_args, get_origin, get_type_hints


class RealizationContractErrorCode(str, Enum):
    """值构造失败的分类；与执行失败及接收拒绝分别表达。"""
    CONTRACT_INVALID_ACTION = "CONTRACT_INVALID_ACTION"
    CONTRACT_INVALID_PLAN = "CONTRACT_INVALID_PLAN"
    CONTRACT_INVALID_EXECUTION_CONTEXT = "CONTRACT_INVALID_EXECUTION_CONTEXT"
    CONTRACT_INVALID_OUTPUT = "CONTRACT_INVALID_OUTPUT"
    CONTRACT_INVALID_RECEIPT = "CONTRACT_INVALID_RECEIPT"
    CONTRACT_INVALID_EXECUTION_REPORT = "CONTRACT_INVALID_EXECUTION_REPORT"
    CONTRACT_INVALID_VALUE = "CONTRACT_INVALID_VALUE"


class InvalidRealizationContractError(ValueError):
    """构造参数或字段关系非法，通过只读 code 提供稳定分类。"""
    def __init__(self, message: str, *, code: RealizationContractErrorCode) -> None:
        self._code = code
        super().__init__(message)

    @property
    def code(self) -> RealizationContractErrorCode:
        """返回本次构造失败的稳定错误码。"""
        return self._code


class _ValueMeta(ABCMeta):
    @property
    def __signature__(cls):
        sig = signature(cls.__init__)
        return sig.replace(parameters=tuple(sig.parameters.values())[1:])

    def __call__(cls, *args, **kwargs):
        if not isabstract(cls):
            try:
                signature(cls).bind(*args, **kwargs)
            except TypeError as error:
                raise InvalidRealizationContractError("Invalid constructor arguments", code=cls._code) from error
        return super().__call__(*args, **kwargs)


def _valid(value, annotation, *, blank=False):
    if get_origin(annotation) is UnionType:
        return any(_valid(value, item, blank=blank) for item in get_args(annotation))
    if get_origin(annotation) is tuple:
        return type(value) is tuple and all(_valid(item, get_args(annotation)[0]) for item in value)
    if annotation is str:
        return isinstance(value, str) and (blank or bool(value.strip()))
    if annotation is int:
        return type(value) is int and value >= 0
    if annotation in (bool, date):
        return type(value) is annotation
    if annotation is bytes:
        return type(value) is bytes and bool(value)
    return isinstance(value, annotation)


class _Value(metaclass=_ValueMeta):
    __slots__ = ()
    _code = RealizationContractErrorCode.CONTRACT_INVALID_VALUE
    _blank_fields = ()

    def _require(self, condition, message):
        if not condition:
            raise InvalidRealizationContractError(message, code=self._code)

    def __post_init__(self):
        annotations = get_type_hints(type(self))
        for field in fields(self):
            self._require(_valid(getattr(self, field.name), annotations[field.name],
                                 blank=field.name in self._blank_fields), f"Invalid {field.name}")
