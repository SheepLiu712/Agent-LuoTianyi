"""按行动类别登记并精确解析内部处理器。"""
from collections.abc import Iterable
from typing import Generic, Protocol, TypeVar

from src.agent.outputs.emitter import OutputEmitter

from src.domain.agent import Action, ActionKind, ActionResult, ExecutionContext

HandlerT = TypeVar("HandlerT")


class ActionHandler(Protocol):
    """实现单项行动，提交内容草稿并报告真实效果。"""

    async def realize(self, action: Action, execution_context: ExecutionContext,
                      outputs: OutputEmitter) -> ActionResult:
        """执行行动并交付输出；返回效果，异常及任务取消由门面处理。"""
        ...


class ActionRouter(Generic[HandlerT]):
    """保存角色私有的行动注册快照，只解析、不执行处理器。"""

    def __init__(self, registrations: Iterable[tuple[ActionKind, HandlerT]]) -> None:
        """消费二元组序列；非法项抛 TypeError，重复或思考提示类别抛 ValueError。"""
        self._handlers: dict[ActionKind, HandlerT] = {}
        for registration in registrations:
            if not isinstance(registration, tuple) or len(registration) != 2:
                raise TypeError("registration must be a pair tuple")
            kind, handler = registration
            if not isinstance(kind, ActionKind) or handler is None:
                raise TypeError("registration requires ActionKind and non-None handler")
            if kind is ActionKind.START_THINKING or kind in self._handlers:
                raise ValueError("stage-owned or duplicate action kind")
            self._handlers[kind] = handler

    def resolve(self, kind: ActionKind) -> HandlerT:
        """返回原处理器引用；错误类型抛 TypeError，未注册抛 KeyError(kind)。"""
        if not isinstance(kind, ActionKind):
            raise TypeError("kind must be ActionKind")
        return self._handlers[kind]
