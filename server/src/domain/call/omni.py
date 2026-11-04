"""一次通话的持续模型会话；不包含供应商协议或持久化行为。"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AudioFrame:
    payload: bytes
    encoding: str
    sample_rate: int
    channels: int
    sequence: int | None = None
    ingress_ns: int | None = None

    def __post_init__(self):
        if not self.payload or not self.encoding or self.sample_rate <= 0 or self.channels <= 0:
            raise ValueError("invalid audio frame")
        if self.sequence is not None and self.sequence < 0:
            raise ValueError("sequence cannot be negative")


@dataclass(frozen=True, slots=True)
class InstructionText:
    kind: Literal["opening", "silence"]
    text: str

    def __post_init__(self):
        if self.kind not in {"opening", "silence"} or not self.text.strip():
            raise ValueError("invalid call instruction")


@dataclass(frozen=True, slots=True)
class SpeechStarted:
    item_id: str


@dataclass(frozen=True, slots=True)
class SpeechStopped:
    item_id: str
    estimated_end_ns: int | None = None


@dataclass(frozen=True, slots=True)
class TranscriptFinal:
    item_id: str
    text: str


@dataclass(frozen=True, slots=True)
class ReplyStarted:
    response_id: str
    item_id: str | None = None


@dataclass(frozen=True, slots=True)
class ReplyFinished:
    response_id: str


@dataclass(frozen=True, slots=True)
class ReplySegment:
    response_id: str
    segment_index: int
    text: str
    tone: str = "中性"

    @property
    def delivery_id(self) -> str:
        return f"{self.response_id}-segment-{self.segment_index}"


@dataclass(frozen=True, slots=True)
class MemoryLookupRequested:
    response_id: str
    tool_call_id: str
    query: str


@dataclass(frozen=True, slots=True)
class MemoryLookupHit:
    memory_id: str
    content: str


@dataclass(frozen=True, slots=True)
class MemoryLookupResult:
    hits: tuple[MemoryLookupHit, ...]
    error: Literal["lookup_failed"] | None = None


OmniEvent = (
    SpeechStarted
    | SpeechStopped
    | TranscriptFinal
    | ReplyStarted
    | ReplyFinished
    | ReplySegment
    | MemoryLookupRequested
)


class OmniSession(Protocol):
    async def push(self, frame: AudioFrame | InstructionText) -> None: ...
    def events(self) -> AsyncIterator[OmniEvent]: ...
    async def submit_tool_result(self, tool_call_id: str, result: MemoryLookupResult) -> None: ...
    async def interrupt(self, response_id: str) -> None: ...
    async def close(self) -> None: ...


class OmniSessionFactory(Protocol):
    async def open(self, call_id: UUID, instructions: str) -> OmniSession: ...
