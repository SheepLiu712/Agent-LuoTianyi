from __future__ import annotations

from abc import ABC, ABCMeta, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from inspect import Signature, signature
from typing import ClassVar, Literal, NoReturn
from zoneinfo import ZoneInfo


StimulusErrorCode = Literal[
    "CONTRACT_INVALID_STIMULUS",
    "CONTRACT_UNSUPPORTED_SCHEMA",
    "CONTRACT_STIMULUS_UNAVAILABLE",
]


class InvalidStimulusError(ValueError):
    """A stable construction failure for the public Stimulus contract."""

    def __init__(self, message: str, *, code: StimulusErrorCode) -> None:
        super().__init__(message)
        self.code = code
        self.retryable: Literal[False] = False


class StimulusKind(str, Enum):
    """Stable discriminator for every registered Stimulus type."""

    TEXT_MESSAGE = "text_message"
    IMAGE_MESSAGE = "image_message"
    VOICE_MESSAGE = "voice_message"
    USER_TYPING = "user_typing"
    IMAGE_SELECTION_OPENED = "image_selection_opened"
    IMAGE_SELECTION_CLOSED = "image_selection_closed"
    TOUCH_INTERACTION = "touch_interaction"
    TOY_VIBRATION = "toy_vibration"
    DEVICE_CONNECTED = "device_connected"
    DEVICE_DISCONNECTED = "device_disconnected"
    PROACTIVE_PROMPT_DUE = "proactive_prompt_due"
    INTERACTION_DEADLINE = "interaction_deadline"
    DYNAMIC_OBSERVED = "dynamic_observed"
    DIARY_PLANNING_DUE = "diary_planning_due"
    WORLD_OBSERVATION = "world_observation"
    DAILY_PLANNING_DUE = "daily_planning_due"
    ACTIVITY_DUE = "activity_due"
    ACTIVITY_STARTED = "activity_started"
    ACTIVITY_OBSERVATION = "activity_observation"
    ACTIVITY_ENDED = "activity_ended"
    SONG_KNOWLEDGE_DISCOVERED = "song_knowledge_discovered"
    SONG_LEARNED = "song_learned"


class StimulusSource(str, Enum):
    """Supplier-independent semantic origin of a Stimulus fact."""

    USER = "user"
    DEVICE = "device"
    WORLD = "world"
    STAGE = "stage"


class DynamicTargetKind(str, Enum):
    """The kind of dynamic message that currently needs a decision."""

    POST = "post"
    COMMENT = "comment"


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


@dataclass(frozen=True, slots=True, kw_only=True)
class Stimulus(ABC, metaclass=_StimulusMeta):
    """Immutable common fields shared by every typed Stimulus."""

    _constructible: ClassVar[bool] = True

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

    def __post_init__(self) -> None:
        _validate_common_fields(
            stimulus_id=self.stimulus_id,
            schema_version=self.schema_version,
            occurred_at=self.occurred_at,
            source=self.source,
            target_character_ids=self.target_character_ids,
            user_id=self.user_id,
            ephemeral=self.ephemeral,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class TextMessage(Stimulus):
    kind: ClassVar[StimulusKind] = StimulusKind.TEXT_MESSAGE

    text: str
    client_msg_id: str

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_nonblank_string(self.text)
        _require_nonblank_string(self.client_msg_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class ImageMessage(Stimulus):
    kind: ClassVar[StimulusKind] = StimulusKind.IMAGE_MESSAGE

    media_ref: MediaRef
    caption: str | None
    client_msg_id: str

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_instance(self.media_ref, MediaRef)
        _require_optional_nonblank_string(self.caption)
        _require_nonblank_string(self.client_msg_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceMessage(Stimulus):
    kind: ClassVar[StimulusKind] = StimulusKind.VOICE_MESSAGE

    media_ref: MediaRef | None
    transcript: str | None
    client_msg_id: str

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_optional_instance(self.media_ref, MediaRef)
        _require_optional_nonblank_string(self.transcript)
        _require_nonblank_string(self.client_msg_id)
        if self.media_ref is None and self.transcript is None:
            _raise_invalid()


@dataclass(frozen=True, slots=True, kw_only=True)
class UserTyping(Stimulus):
    kind: ClassVar[StimulusKind] = StimulusKind.USER_TYPING

    text_length: int

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_nonnegative_int(self.text_length)


@dataclass(frozen=True, slots=True, kw_only=True)
class ImageSelectionOpened(Stimulus):
    kind: ClassVar[StimulusKind] = StimulusKind.IMAGE_SELECTION_OPENED


@dataclass(frozen=True, slots=True, kw_only=True)
class ImageSelectionClosed(Stimulus):
    kind: ClassVar[StimulusKind] = StimulusKind.IMAGE_SELECTION_CLOSED


@dataclass(frozen=True, slots=True, kw_only=True)
class TouchInteraction(Stimulus):
    kind: ClassVar[StimulusKind] = StimulusKind.TOUCH_INTERACTION

    body_regions: tuple[BodyRegion, ...]
    click_frequency: TouchClickFrequency | None

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_tuple_of(self.body_regions, BodyRegion, allow_empty=False)
        _require_optional_instance(self.click_frequency, TouchClickFrequency)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProactivePromptDue(Stimulus):
    kind: ClassVar[StimulusKind] = StimulusKind.PROACTIVE_PROMPT_DUE

    reason: ProactiveReason
    due_at: datetime
    dedup_key: str
    fact_refs: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_instance(self.reason, ProactiveReason)
        _require_aware_datetime(self.due_at)
        _require_nonblank_string(self.dedup_key)
        _require_tuple_of(self.fact_refs, EvidenceRef)


@dataclass(frozen=True, slots=True, kw_only=True)
class InteractionDeadline(Stimulus):
    kind: ClassVar[StimulusKind] = StimulusKind.INTERACTION_DEADLINE


@dataclass(frozen=True, slots=True, kw_only=True)
class DynamicObserved(Stimulus):
    kind: ClassVar[StimulusKind] = StimulusKind.DYNAMIC_OBSERVED

    dynamic_id: str
    target_message_id: str
    target_kind: DynamicTargetKind
    messages: tuple[DynamicMessage, ...]
    revision: int

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_nonblank_string(self.dynamic_id)
        _require_nonblank_string(self.target_message_id)
        _require_instance(self.target_kind, DynamicTargetKind)
        _require_tuple_of(self.messages, DynamicMessage, allow_empty=False)
        _require_nonnegative_int(self.revision)

        message_ids = tuple(message.message_id for message in self.messages)
        if len(message_ids) != len(set(message_ids)):
            _raise_invalid()
        if self.messages[0].message_id != self.dynamic_id:
            _raise_invalid()
        if self.messages[0].parent_message_id is not None:
            _raise_invalid()

        prior_ids = {self.dynamic_id}
        for message in self.messages[1:]:
            if message.parent_message_id not in prior_ids:
                _raise_invalid()
            prior_ids.add(message.message_id)

        if message_ids.count(self.target_message_id) != 1:
            _raise_invalid()
        if self.target_kind is DynamicTargetKind.POST:
            if self.target_message_id != self.dynamic_id:
                _raise_invalid()
        elif self.target_message_id == self.dynamic_id:
            _raise_invalid()


@dataclass(frozen=True, slots=True, kw_only=True)
class DiaryPlanningDue(Stimulus):
    kind: ClassVar[StimulusKind] = StimulusKind.DIARY_PLANNING_DUE

    local_date: date
    timezone: ZoneInfo
    trigger_id: str

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        if type(self.local_date) is not date:
            _raise_invalid()
        _require_instance(self.timezone, ZoneInfo)
        _require_nonblank_string(self.trigger_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class WorldObservation(Stimulus):
    kind: ClassVar[StimulusKind] = StimulusKind.WORLD_OBSERVATION

    observation_kind: WorldObservationKind
    fact: WorldFact
    evidence_refs: tuple[EvidenceRef, ...]
    world_revision: int

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_instance(self.observation_kind, WorldObservationKind)
        _require_instance(self.fact, WorldFact)
        _require_tuple_of(self.evidence_refs, EvidenceRef)
        _require_nonnegative_int(self.world_revision)


@dataclass(frozen=True, slots=True, kw_only=True)
class ActivityObservation(Stimulus):
    kind: ClassVar[StimulusKind] = StimulusKind.ACTIVITY_OBSERVATION

    activity_id: str
    observation: ActivityFact
    activity_revision: int

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_nonblank_string(self.activity_id)
        _require_instance(self.observation, ActivityFact)
        _require_nonnegative_int(self.activity_revision)


@dataclass(frozen=True, slots=True, kw_only=True)
class SongKnowledgeDiscovered(Stimulus):
    kind: ClassVar[StimulusKind] = StimulusKind.SONG_KNOWLEDGE_DISCOVERED

    source_ref: SourceRef
    external_song_id: str
    revision: int
    candidate: SongKnowledgeCandidate
    fetched_at: datetime

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_instance(self.source_ref, SourceRef)
        _require_nonblank_string(self.external_song_id)
        _require_nonnegative_int(self.revision)
        _require_instance(self.candidate, SongKnowledgeCandidate)
        _require_aware_datetime(self.fetched_at)


@dataclass(frozen=True, slots=True, kw_only=True)
class SongLearned(Stimulus):
    kind: ClassVar[StimulusKind] = StimulusKind.SONG_LEARNED

    learning_job_id: str
    song_id: str
    completed_at: datetime

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_nonblank_string(self.learning_job_id)
        _require_nonblank_string(self.song_id)
        _require_aware_datetime(self.completed_at)


class ToyVibration(Stimulus):
    _constructible = False
    kind = StimulusKind.TOY_VIBRATION


class DeviceConnected(Stimulus):
    _constructible = False
    kind = StimulusKind.DEVICE_CONNECTED


class DeviceDisconnected(Stimulus):
    _constructible = False
    kind = StimulusKind.DEVICE_DISCONNECTED


class DailyPlanningDue(Stimulus):
    _constructible = False
    kind = StimulusKind.DAILY_PLANNING_DUE


class ActivityDue(Stimulus):
    _constructible = False
    kind = StimulusKind.ACTIVITY_DUE


class ActivityStarted(Stimulus):
    _constructible = False
    kind = StimulusKind.ACTIVITY_STARTED


class ActivityEnded(Stimulus):
    _constructible = False
    kind = StimulusKind.ACTIVITY_ENDED


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
            "Unsupported Stimulus schema version",
            code="CONTRACT_UNSUPPORTED_SCHEMA",
        )
    _require_aware_datetime(occurred_at)
    _require_instance(source, StimulusSource)
    _require_string_tuple(target_character_ids, allow_empty=False)
    _require_optional_nonblank_string(user_id)
    if type(ephemeral) is not bool:
        _raise_invalid()


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
