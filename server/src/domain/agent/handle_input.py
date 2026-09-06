"""One handle request and its stage-owned cooperative cancellation signal."""

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
    SUPERSEDED = "superseded"
    NO_LONGER_NEEDED = "no_longer_needed"


class CancellationToken(metaclass=_HandleInputMeta):
    """Shared within one stage event loop; the first cancellation reason wins."""

    __slots__ = ("_reason",)
    _error_code = HandleInputErrorCode.CONTRACT_INVALID_CANCELLATION

    def __init__(self) -> None:
        self._reason: CancellationReason | None = None

    @property
    def is_cancelled(self) -> bool:
        return self._reason is not None

    @property
    def reason(self) -> CancellationReason | None:
        return self._reason

    @_checked_arguments(HandleInputErrorCode.CONTRACT_INVALID_CANCELLATION)
    def cancel(self, reason: CancellationReason) -> bool:
        """Publish the first reason; repeated valid cancellation returns False."""
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
    """Frozen decision input retaining the caller's live cancellation token."""

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
