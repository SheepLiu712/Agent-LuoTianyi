from __future__ import annotations

from dataclasses import dataclass

from ._stimulus_contract import (
    _ContractValueMeta,
    _raise_invalid,
    _require_instance,
    _require_nonblank_string,
    _require_nonnegative_int,
    _require_optional_nonblank_string,
    _require_string_tuple,
    _require_tuple_of,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class MediaRef(metaclass=_ContractValueMeta):
    media_id: str

    def __post_init__(self) -> None:
        _require_nonblank_string(self.media_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class EvidenceRef(metaclass=_ContractValueMeta):
    evidence_id: str

    def __post_init__(self) -> None:
        _require_nonblank_string(self.evidence_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceRef(metaclass=_ContractValueMeta):
    source_id: str

    def __post_init__(self) -> None:
        _require_nonblank_string(self.source_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class BodyRegion(metaclass=_ContractValueMeta):
    value: str

    def __post_init__(self) -> None:
        _require_nonblank_string(self.value)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProactiveReason(metaclass=_ContractValueMeta):
    value: str

    def __post_init__(self) -> None:
        _require_nonblank_string(self.value)


@dataclass(frozen=True, slots=True, kw_only=True)
class WorldObservationKind(metaclass=_ContractValueMeta):
    value: str

    def __post_init__(self) -> None:
        _require_nonblank_string(self.value)


@dataclass(frozen=True, slots=True, kw_only=True)
class ActorRef(metaclass=_ContractValueMeta):
    actor_id: str
    display_name: str | None

    def __post_init__(self) -> None:
        _require_nonblank_string(self.actor_id)
        _require_optional_nonblank_string(self.display_name)


@dataclass(frozen=True, slots=True, kw_only=True)
class TouchClickFrequency(metaclass=_ContractValueMeta):
    count_10s: int
    count_30s: int

    def __post_init__(self) -> None:
        _require_nonnegative_int(self.count_10s)
        _require_nonnegative_int(self.count_30s)
        if self.count_10s > self.count_30s:
            _raise_invalid()


@dataclass(frozen=True, slots=True, kw_only=True)
class DynamicMessage(metaclass=_ContractValueMeta):
    message_id: str
    parent_message_id: str | None
    author_ref: ActorRef
    text: str
    media_refs: tuple[MediaRef, ...]

    def __post_init__(self) -> None:
        _require_nonblank_string(self.message_id)
        _require_optional_nonblank_string(self.parent_message_id)
        _require_instance(self.author_ref, ActorRef)
        if not isinstance(self.text, str):
            _raise_invalid()
        _require_tuple_of(self.media_refs, MediaRef)
        if not self.text.strip() and not self.media_refs:
            _raise_invalid()


@dataclass(frozen=True, slots=True, kw_only=True)
class WorldFact(metaclass=_ContractValueMeta):
    fact_id: str
    summary: str

    def __post_init__(self) -> None:
        _require_nonblank_string(self.fact_id)
        _require_nonblank_string(self.summary)


@dataclass(frozen=True, slots=True, kw_only=True)
class ActivityFact(metaclass=_ContractValueMeta):
    fact_id: str
    summary: str

    def __post_init__(self) -> None:
        _require_nonblank_string(self.fact_id)
        _require_nonblank_string(self.summary)


@dataclass(frozen=True, slots=True, kw_only=True)
class SongKnowledgeCandidate(metaclass=_ContractValueMeta):
    song_name: str
    uploader: str | None
    singers: tuple[str, ...]
    introduction: str
    lyrics: str | None
    lyric_keywords: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_nonblank_string(self.song_name)
        _require_optional_nonblank_string(self.uploader)
        _require_string_tuple(self.singers)
        _require_nonblank_string(self.introduction)
        _require_optional_nonblank_string(self.lyrics)
        _require_string_tuple(self.lyric_keywords)
