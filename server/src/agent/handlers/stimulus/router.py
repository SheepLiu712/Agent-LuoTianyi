"""按刺激类别登记并精确解析内部处理器。"""
from collections.abc import Iterable
from typing import Generic, Protocol, TypeVar

from src.domain.agent import ActionPlanSink, HandleStimulusRequest, HandlingReport, StimulusKind

HandlerT = TypeVar("HandlerT")


class StimulusHandler(Protocol):
    """处理单次刺激，使用本次受限计划接收器并返回真实结算。"""

    async def handle(self, request: HandleStimulusRequest, plans: ActionPlanSink) -> HandlingReport:
        """处理请求并交付计划；返回结算，异常及任务取消由门面处理。"""
        ...


class StimulusRouter(Generic[HandlerT]):
    """保存角色私有的刺激注册快照，只解析、不执行处理器。"""

    def __init__(self, registrations: Iterable[tuple[StimulusKind, HandlerT]]) -> None:
        """消费二元组序列；非法项抛 TypeError，重复类别抛 ValueError。"""
        self._handlers: dict[StimulusKind, HandlerT] = {}
        for registration in registrations:
            if not isinstance(registration, tuple) or len(registration) != 2:
                raise TypeError("registration must be a pair tuple")
            kind, handler = registration
            if not isinstance(kind, StimulusKind) or handler is None:
                raise TypeError("registration requires StimulusKind and non-None handler")
            if kind in self._handlers:
                raise ValueError("duplicate stimulus kind")
            self._handlers[kind] = handler

    def resolve(self, kind: StimulusKind) -> HandlerT:
        """返回原处理器引用；错误类型抛 TypeError，未注册抛 KeyError(kind)。"""
        if not isinstance(kind, StimulusKind):
            raise TypeError("kind must be StimulusKind")
        return self._handlers[kind]
