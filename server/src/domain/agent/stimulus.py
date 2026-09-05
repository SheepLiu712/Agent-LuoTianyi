from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Literal, NoReturn


StimulusErrorCode = Literal[
    "CONTRACT_INVALID_STIMULUS",
    "CONTRACT_UNSUPPORTED_SCHEMA",
]


class InvalidStimulusError(ValueError):
    """A stable construction failure for a typed stimulus."""

    def __init__(self, message: str, *, code: StimulusErrorCode) -> None:
        super().__init__(message)
        self.code = code
        self.retryable: Literal[False] = False


class StimulusKind(str, Enum):
    """Stable discriminator for registered stimulus variants."""

    TEXT_MESSAGE = "text_message"


class StimulusSource(str, Enum):
    """Supplier-independent semantic origin of a stimulus fact."""

    USER = "user"
    DEVICE = "device"
    WORLD = "world"
    STAGE = "stage"


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class Stimulus(ABC):
    """Immutable common fields shared by every typed stimulus."""

    stimulus_id: str
    schema_version: int
    occurred_at: datetime
    source: StimulusSource
    target_character_ids: tuple[str, ...]
    user_id: str | None
    ephemeral: bool

    @property
    @abstractmethod
    def kind(self) -> StimulusKind:
        """Return the fixed discriminator selected by the concrete type."""


_MISSING: Any = object()


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class TextMessage(Stimulus):
    """An immutable complete text message submitted for Agent handling."""

    text: str
    client_msg_id: str

    def __init__(
        self,
        *,
        stimulus_id: str = _MISSING,
        schema_version: int = _MISSING,
        occurred_at: datetime = _MISSING,
        source: StimulusSource = _MISSING,
        target_character_ids: tuple[str, ...] = _MISSING,
        user_id: str | None = _MISSING,
        ephemeral: bool = _MISSING,
        text: str = _MISSING,
        client_msg_id: str = _MISSING,
    ) -> None:
        fields = {
            "stimulus_id": stimulus_id,
            "schema_version": schema_version,
            "occurred_at": occurred_at,
            "source": source,
            "target_character_ids": target_character_ids,
            "user_id": user_id,
            "ephemeral": ephemeral,
            "text": text,
            "client_msg_id": client_msg_id,
        }
        if any(value is _MISSING for value in fields.values()):
            raise InvalidStimulusError(
                "Required stimulus fields are missing",
                code="CONTRACT_INVALID_STIMULUS",
            )

        _validate_common_fields(
            stimulus_id=stimulus_id,
            schema_version=schema_version,
            occurred_at=occurred_at,
            source=source,
            target_character_ids=target_character_ids,
            user_id=user_id,
            ephemeral=ephemeral,
        )
        _require_nonblank_string(text)
        _require_nonblank_string(client_msg_id)

        object.__setattr__(self, "stimulus_id", stimulus_id)
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "occurred_at", occurred_at)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "target_character_ids", target_character_ids)
        object.__setattr__(self, "user_id", user_id)
        object.__setattr__(self, "ephemeral", ephemeral)
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "client_msg_id", client_msg_id)

    @property
    def kind(self) -> StimulusKind:
        return StimulusKind.TEXT_MESSAGE


def _validate_common_fields(
    *,
    stimulus_id: object,
    schema_version: object,
    occurred_at: object,
    source: object,
    target_character_ids: object,
    user_id: object,
    ephemeral: object,
) -> None:
    _require_nonblank_string(stimulus_id)

    if type(schema_version) is not int:
        _raise_invalid()
    if schema_version != 1:
        raise InvalidStimulusError(
            "Unsupported stimulus schema version",
            code="CONTRACT_UNSUPPORTED_SCHEMA",
        )

    if not isinstance(occurred_at, datetime):
        _raise_invalid()
    try:
        is_aware = occurred_at.tzinfo is not None and occurred_at.utcoffset() is not None
    except (OverflowError, TypeError, ValueError):
        is_aware = False
    if not is_aware:
        _raise_invalid()

    if not isinstance(source, StimulusSource):
        _raise_invalid()

    if not isinstance(target_character_ids, tuple) or not target_character_ids:
        _raise_invalid()
    if any(not _is_nonblank_string(item) for item in target_character_ids):
        _raise_invalid()

    if user_id is not None and not _is_nonblank_string(user_id):
        _raise_invalid()

    if type(ephemeral) is not bool:
        _raise_invalid()


def _is_nonblank_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _require_nonblank_string(value: object) -> None:
    if not _is_nonblank_string(value):
        _raise_invalid()


def _raise_invalid() -> NoReturn:
    raise InvalidStimulusError(
        "Invalid stimulus field",
        code="CONTRACT_INVALID_STIMULUS",
    )
