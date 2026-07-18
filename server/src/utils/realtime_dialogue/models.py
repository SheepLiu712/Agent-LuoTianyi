from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RealtimeEventType(str, Enum):
    SESSION_UPDATE = "session.update"
    AUDIO_APPEND = "input_audio_buffer.append"
    CONTEXT_ITEM_CREATE = "conversation.item.create"
    CONTEXT_ITEM_DELETE = "conversation.item.delete"
    RESPONSE_CREATE = "response.create"
    RESPONSE_CANCEL = "response.cancel"

    SPEECH_STARTED = "input_audio_buffer.speech_started"
    SPEECH_STOPPED = "input_audio_buffer.speech_stopped"
    INPUT_TRANSCRIPTION_COMPLETED = "conversation.item.input_audio_transcription.completed"
    RESPONSE_CREATED = "response.created"
    TEXT_DELTA = "response.text.delta"
    OUTPUT_TEXT_DELTA = "response.output_text.delta"
    AUDIO_TRANSCRIPT_DELTA = "response.audio_transcript.delta"
    OUTPUT_AUDIO_TRANSCRIPT_DELTA = "response.output_audio_transcript.delta"
    FUNCTION_ARGUMENTS_DELTA = "response.function_call_arguments.delta"
    FUNCTION_ARGUMENTS_DONE = "response.function_call_arguments.done"
    OUTPUT_ITEM_DONE = "response.output_item.done"
    CONTENT_PART_DONE = "response.content_part.done"
    RESPONSE_DONE = "response.done"
    ERROR = "error"

@dataclass(frozen=True)
class RealtimeToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]

    def as_payload(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class RealtimeEvent:
    type: RealtimeEventType | str
    raw: dict[str, Any] = field(default_factory=dict)
    event_id: str | None = None
    response_id: str | None = None
    item_id: str | None = None
    call_id: str | None = None
    delta: str = ""
    transcript: str = ""
    name: str | None = None
    arguments: str = ""
    usage: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

