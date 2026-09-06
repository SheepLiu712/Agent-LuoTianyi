"""单次 handle 请求及其由 stage 发布的协作式取消信号。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import ClassVar

from ._handle_input_contract import (
    HandleInputErrorCode,
    _checked_arguments,
    _HandleInputMeta,
    _nonblank,
    _require,
)
from .interaction_snapshot import InteractionSnapshot
from .stimulus import Stimulus, StimulusKind


class CancellationReason(str, Enum):
    """取消原因：SUPERSEDED 表示处理已过时，NO_LONGER_NEEDED 表示已无需处理。"""

    SUPERSEDED = "superseded"
    NO_LONGER_NEEDED = "no_longer_needed"


class CancellationToken(metaclass=_HandleInputMeta):
    """同一 stage 事件循环内共享的可变取消信号，保留首次取消原因。

    初始 is_cancelled 为 False、reason 为 None。stage 调用 cancel 发布状态，
    持有同一令牌的 Agent 可通过只读属性观察取消状态和原因。
    """

    __slots__ = ("_reason",)
    _error_code = HandleInputErrorCode.CONTRACT_INVALID_CANCELLATION

    def __init__(self) -> None:
        self._reason: CancellationReason | None = None

    @property
    def is_cancelled(self) -> bool:
        """是否已经发布取消信号。"""
        return self._reason is not None

    @property
    def reason(self) -> CancellationReason | None:
        """首次取消的原因；尚未取消时为 None。"""
        return self._reason

    @_checked_arguments(HandleInputErrorCode.CONTRACT_INVALID_CANCELLATION)
    def cancel(self, reason: CancellationReason) -> bool:
        """首次发布有效原因时返回 True，之后的有效调用返回 False 并保留原原因。

        原因必须是 CancellationReason，非法参数抛出 InvalidHandleInputError，
        错误码为 CONTRACT_INVALID_CANCELLATION。
        """
        _require(isinstance(reason, CancellationReason), "cancellation reason", self._error_code)
        if self._reason is not None:
            return False
        # A single state assignment keeps reason and derived is_cancelled consistent.
        self._reason = reason
        return True


_CONTENT_TRIGGER_KINDS = frozenset({
    StimulusKind.TEXT_MESSAGE, StimulusKind.IMAGE_MESSAGE, StimulusKind.VOICE_MESSAGE,
})


@dataclass(frozen=True, slots=True, kw_only=True)
class HandleStimulusRequest(metaclass=_HandleInputMeta):
    """单次决策的不可变输入，包含请求 ID、触发刺激、交互快照及共享取消令牌。

    文本、图片和语音触发刺激必须在 pending_stimuli 中出现；同 ID 的待处理刺激
    必须与触发刺激完整值相等。cancellation 保留调用方传入的同一可变对象。
    字段以关键字显式传入，非法请求抛出 InvalidHandleInputError。
    """

    _error_code: ClassVar[HandleInputErrorCode] = HandleInputErrorCode.CONTRACT_INVALID_HANDLE_REQUEST

    request_id: str
    stimulus: Stimulus
    interaction: InteractionSnapshot
    cancellation: CancellationToken

    def __post_init__(self) -> None:
        code = self._error_code
        _require(_nonblank(self.request_id), "request_id", code)
        _require(isinstance(self.stimulus, Stimulus), "stimulus", code)
        _require(isinstance(self.interaction, InteractionSnapshot), "interaction", code)
        _require(isinstance(self.cancellation, CancellationToken), "cancellation", code)
        matching = tuple(
            item for item in self.interaction.pending_stimuli
            if item.stimulus_id == self.stimulus.stimulus_id
        )
        if self.stimulus.kind in _CONTENT_TRIGGER_KINDS:
            _require(len(matching) == 1, "content trigger missing from pending", code)
        _require(all(item == self.stimulus for item in matching), "trigger/pending content mismatch", code)
