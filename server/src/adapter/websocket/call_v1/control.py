"""Strict, pure parser and encoder for candidate ``call.v1`` control frames.

This module validates one control frame only.  Session ordering, replay and
stream registration deliberately remain Adapter responsibilities.
"""

from __future__ import annotations

import json
import re
from typing import Literal, Mapping, TypedDict, Union

ControlTransport = Literal["chat_ws", "call_ws"]
ControlSender = Literal["client", "server"]


class SwitchPrepareMessage(TypedDict):
    protocol: Literal["call.v1"]
    type: Literal["call.switch_prepare"]
    client_request_id: str
    character_id: str


class SwitchReadyMessage(SwitchPrepareMessage):
    type: Literal["call.switch_ready"]


class StartMessage(TypedDict):
    protocol: Literal["call.v1"]
    type: Literal["call.start"]
    seq: int
    client_request_id: str
    character_id: str
    audio: dict[str, object]


class StateMessage(TypedDict):
    protocol: Literal["call.v1"]
    type: Literal["call.state"]
    seq: int
    call_id: str
    client_request_id: str
    state: str


class ActiveMessage(TypedDict):
    protocol: Literal["call.v1"]
    type: Literal["call.active"]
    seq: int
    call_id: str
    connected_at_ms: int


class HangupMessage(TypedDict):
    protocol: Literal["call.v1"]
    type: Literal["call.hangup"]
    seq: int
    call_id: str
    reason: str


class EndedMessage(TypedDict):
    protocol: Literal["call.v1"]
    type: Literal["call.ended"]
    seq: int
    call_id: str
    outcome: str
    end_reason: str
    active_duration_ms: int


class ResumeMessage(TypedDict):
    protocol: Literal["call.v1"]
    type: Literal["call.resume"]
    call_id: str
    character_id: str
    last_contiguous_server_seq: int


class ResumedMessage(TypedDict):
    protocol: Literal["call.v1"]
    type: Literal["call.resumed"]
    call_id: str
    character_id: str
    last_contiguous_client_seq: int
    last_contiguous_server_seq: int


class AckMessage(TypedDict):
    protocol: Literal["call.v1"]
    type: Literal["ack"]
    call_id: str
    ack_seq: int


class NackMessage(TypedDict):
    protocol: Literal["call.v1"]
    type: Literal["nack"]
    call_id: str
    missing_seq: int


class StreamStartedMessage(TypedDict):
    protocol: Literal["call.v1"]
    type: Literal["audio.stream_started"]
    seq: int
    call_id: str
    audio_route: Literal["CALL"]
    stream_id: int
    response_id: str
    encoding: Literal["pcm_s16le"]
    sample_rate: Literal[24000]
    channels: Literal[1]


class PlaybackCompletedMessage(TypedDict):
    protocol: Literal["call.v1"]
    type: Literal["playback.completed"]
    seq: int
    call_id: str
    response_id: str
    stream_id: int


class PlaybackStopMessage(TypedDict):
    protocol: Literal["call.v1"]
    type: Literal["playback.stop"]
    seq: int
    call_id: str
    response_id: str
    stream_id: int
    retire_server_seq: dict[str, int]
    reason: Literal["user_interrupted"]


class PlaybackStoppedMessage(TypedDict):
    protocol: Literal["call.v1"]
    type: Literal["playback.stopped"]
    seq: int
    call_id: str
    response_id: str
    stop_seq: int


class ErrorMessage(TypedDict, total=False):
    protocol: Literal["call.v1"]
    type: Literal["error"]
    code: str
    message: str
    retryable: bool
    request_type: str
    request_seq: int
    client_request_id: str
    call_id: str


ControlMessage = Union[
    SwitchPrepareMessage,
    SwitchReadyMessage,
    StartMessage,
    StateMessage,
    ActiveMessage,
    HangupMessage,
    EndedMessage,
    ResumeMessage,
    ResumedMessage,
    AckMessage,
    NackMessage,
    StreamStartedMessage,
    PlaybackCompletedMessage,
    PlaybackStopMessage,
    PlaybackStoppedMessage,
    ErrorMessage,
]

_UINT32_MAX = 4_294_967_295
_SAFE_INTEGER_MAX = 9_007_199_254_740_991
_MAX_RAW_BYTES = 16_384
_CALL_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class ControlProtocolError(ValueError):
    """A normalized control-protocol failure with a stable code and path."""

    def __init__(self, code: str, path: str) -> None:
        self.code = code
        self.path = path
        super().__init__(f"{code} at {path}")


class _Pairs(list[tuple[object, object]]):
    pass


class _Integer(int):
    def __new__(cls, value: str) -> _Integer:
        result = super().__new__(cls, value)
        result.lexeme = value
        return result


class _Float(float):
    pass


_FIELDS: dict[str, tuple[str, ...]] = {
    "call.switch_prepare": ("protocol", "type", "client_request_id", "character_id"),
    "call.switch_ready": ("protocol", "type", "client_request_id", "character_id"),
    "call.start": ("protocol", "type", "seq", "client_request_id", "character_id", "audio"),
    "call.state": ("protocol", "type", "seq", "call_id", "client_request_id", "state"),
    "call.active": ("protocol", "type", "seq", "call_id", "connected_at_ms"),
    "call.hangup": ("protocol", "type", "seq", "call_id", "reason"),
    "call.ended": ("protocol", "type", "seq", "call_id", "outcome", "end_reason", "active_duration_ms"),
    "call.resume": ("protocol", "type", "call_id", "character_id", "last_contiguous_server_seq"),
    "call.resumed": (
        "protocol",
        "type",
        "call_id",
        "character_id",
        "last_contiguous_client_seq",
        "last_contiguous_server_seq",
    ),
    "ack": ("protocol", "type", "call_id", "ack_seq"),
    "nack": ("protocol", "type", "call_id", "missing_seq"),
    "audio.stream_started": (
        "protocol",
        "type",
        "seq",
        "call_id",
        "audio_route",
        "stream_id",
        "response_id",
        "encoding",
        "sample_rate",
        "channels",
    ),
    "playback.completed": ("protocol", "type", "seq", "call_id", "response_id", "stream_id"),
    "playback.stop": ("protocol", "type", "seq", "call_id", "response_id", "stream_id", "retire_server_seq", "reason"),
    "playback.stopped": ("protocol", "type", "seq", "call_id", "response_id", "stop_seq"),
    "error": (
        "protocol",
        "type",
        "code",
        "message",
        "retryable",
        "request_type",
        "request_seq",
        "client_request_id",
        "call_id",
    ),
}
_OPTIONAL = {"error": {"request_type", "request_seq", "client_request_id", "call_id"}}
_ROUTES = {
    "call.switch_prepare": (("chat_ws",), ("client",)),
    "call.switch_ready": (("chat_ws",), ("server",)),
    "call.start": (("call_ws",), ("client",)),
    "call.state": (("call_ws",), ("server",)),
    "call.active": (("call_ws",), ("server",)),
    "call.hangup": (("call_ws",), ("client",)),
    "call.ended": (("call_ws",), ("server",)),
    "call.resume": (("call_ws",), ("client",)),
    "call.resumed": (("call_ws",), ("server",)),
    "ack": (("call_ws",), ("client", "server")),
    "nack": (("call_ws",), ("client", "server")),
    "audio.stream_started": (("call_ws",), ("server",)),
    "playback.completed": (("call_ws",), ("client",)),
    "playback.stop": (("call_ws",), ("server",)),
    "playback.stopped": (("call_ws",), ("client",)),
    "error": (("chat_ws", "call_ws"), ("client", "server")),
}
_ENUMS = {
    "state": {"preparing", "ringing"},
    "outcome": {"connected", "cancelled_before_answer", "declined"},
    "end_reason": {
        "user_hangup",
        "agent_hangup",
        "declined",
        "setup_timeout",
        "time_limit",
        "provider_failed",
        "recovery_timeout",
        "system_failure",
    },
    "audio_route": {"CALL"},
    "encoding": {"pcm_s16le"},
}


def decode_control_text(text: str | bytes, *, sender: ControlSender, transport: ControlTransport) -> ControlMessage:
    """Decode and validate one raw control frame at the protocol boundary."""
    raw = _strict_text(text)
    if _utf8_size(raw, text) > _MAX_RAW_BYTES:
        raise ControlProtocolError("CONTROL_TOO_LARGE", "$")
    try:
        parsed = json.loads(
            raw, object_pairs_hook=_Pairs, parse_int=_Integer, parse_float=_Float, parse_constant=_reject_constant
        )
    except _JsonConstant as error:
        raise ControlProtocolError("BAD_JSON", _constant_path(raw, error.token)) from None
    except (json.JSONDecodeError, RecursionError):
        raise ControlProtocolError("BAD_JSON", "$") from None
    try:
        _reject_duplicates_and_surrogates(parsed)
        if not isinstance(parsed, _Pairs):
            raise ControlProtocolError("TOP_LEVEL_NOT_OBJECT", "$")
        return _validate(_pairs_to_dict(parsed), sender=sender, transport=transport)
    except RecursionError:
        raise ControlProtocolError("BAD_JSON", "$") from None


def encode_control_message(message: Mapping[str, object], *, sender: ControlSender, transport: ControlTransport) -> str:
    """Validate and encode a control message using the contract's field order."""
    if not isinstance(message, Mapping):
        raise ControlProtocolError("TOP_LEVEL_NOT_OBJECT", "$")
    validated = _validate(dict(message), sender=sender, transport=transport)
    ordered = _ordered_message(validated)
    encoded = json.dumps(ordered, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    # This also keeps encoder and raw parser validation at the exact same boundary.
    decode_control_text(encoded, sender=sender, transport=transport)
    return encoded


def _ordered_message(message: ControlMessage) -> dict[str, object]:
    ordered = {field: message[field] for field in _FIELDS[message["type"]] if field in message}
    if "audio" in ordered:
        audio = ordered["audio"]
        assert isinstance(audio, dict)
        ordered["audio"] = {field: audio[field] for field in ("encoding", "sample_rate", "channels")}
    if "retire_server_seq" in ordered:
        retired = ordered["retire_server_seq"]
        assert isinstance(retired, dict)
        ordered["retire_server_seq"] = {field: retired[field] for field in ("from", "through")}
    return ordered


def _strict_text(text: str | bytes) -> str:
    try:
        if isinstance(text, bytes):
            if len(text) > _MAX_RAW_BYTES:
                raise ControlProtocolError("CONTROL_TOO_LARGE", "$")
            return text.decode("utf-8", "strict")
        if isinstance(text, str):
            text.encode("utf-8", "strict")
            return text
    except UnicodeError:
        pass
    raise ControlProtocolError("BAD_JSON", "$")


def _utf8_size(raw: str, original: str | bytes) -> int:
    """Use byte length directly for bytes to reject oversized input early."""
    return len(original) if isinstance(original, bytes) else len(raw.encode("utf-8"))


class _JsonConstant(Exception):
    def __init__(self, token: str) -> None:
        self.token = token


def _reject_constant(token: str) -> None:
    raise _JsonConstant(token)


def _constant_path(raw: str, token: str) -> str:
    match = re.search(r'"([^"\\]+)"\s*:\s*' + re.escape(token) + r"(?=\s*[,}])", raw)
    return f"$.{match.group(1)}" if match else "$"


def _reject_duplicates_and_surrogates(value: object, path: str = "$") -> None:
    if isinstance(value, _Pairs):
        seen: set[object] = set()
        for key, child in value:
            if not isinstance(key, str):
                raise ControlProtocolError("BAD_JSON", path)
            if key in seen:
                raise ControlProtocolError("DUPLICATE_FIELD", f"{path}.{key}")
            seen.add(key)
            _reject_scalar_surrogate(key, path)
            _reject_duplicates_and_surrogates(child, f"{path}.{key}")
    elif isinstance(value, list):
        for child in value:
            _reject_duplicates_and_surrogates(child, path)
    elif isinstance(value, str):
        _reject_scalar_surrogate(value, path)


def _reject_scalar_surrogate(value: str, path: str) -> None:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ControlProtocolError("BAD_JSON", path)


def _pairs_to_dict(value: object) -> object:
    if isinstance(value, _Pairs):
        return {key: _pairs_to_dict(child) for key, child in value}
    if isinstance(value, list):
        return [_pairs_to_dict(child) for child in value]
    return value


def _validate(message: dict[str, object], *, sender: str, transport: str) -> ControlMessage:
    message_type = _validate_discriminator(message)
    _validate_route(message_type, sender=sender, transport=transport)
    _validate_shape(message, message_type)
    _validate_types(message, message_type)
    _validate_ranges_and_values(message, message_type)
    _validate_enums(message, message_type)
    _validate_cross_fields(message, message_type)
    return message  # type: ignore[return-value]


def _validate_discriminator(message: dict[str, object]) -> str:
    if "protocol" not in message:
        raise ControlProtocolError("MISSING_FIELD", "$.protocol")
    protocol = message["protocol"]
    if not isinstance(protocol, str):
        raise ControlProtocolError("INVALID_FIELD_TYPE", "$.protocol")
    if protocol != "call.v1":
        raise ControlProtocolError("UNSUPPORTED_PROTOCOL", "$.protocol")
    if "type" not in message:
        raise ControlProtocolError("MISSING_FIELD", "$.type")
    message_type = message["type"]
    if not isinstance(message_type, str):
        raise ControlProtocolError("INVALID_FIELD_TYPE", "$.type")
    if message_type not in _FIELDS:
        raise ControlProtocolError("UNKNOWN_TYPE", "$.type")
    return message_type


def _validate_route(message_type: str, *, sender: str, transport: str) -> None:
    expected_transports, expected_senders = _ROUTES[message_type]
    if transport not in expected_transports:
        raise ControlProtocolError("INVALID_TRANSPORT", "$")
    sender = {"client_to_server": "client", "server_to_client": "server"}.get(sender, sender)
    if sender not in expected_senders:
        raise ControlProtocolError("INVALID_DIRECTION", "$")


def _validate_shape(message: dict[str, object], message_type: str) -> None:
    required = set(_FIELDS[message_type]) - _OPTIONAL.get(message_type, set())
    for field in _FIELDS[message_type]:
        if field in required and field not in message:
            raise ControlProtocolError("MISSING_FIELD", f"$.{field}")
    allowed = set(_FIELDS[message_type])
    for field in message:
        if field not in allowed:
            raise ControlProtocolError("UNKNOWN_FIELD", f"$.{field}")


def _validate_types(message: dict[str, object], message_type: str) -> None:
    int_fields = {
        "seq",
        "stream_id",
        "sample_rate",
        "channels",
        "connected_at_ms",
        "active_duration_ms",
        "last_contiguous_server_seq",
        "last_contiguous_client_seq",
        "ack_seq",
        "missing_seq",
        "request_seq",
        "stop_seq",
    }
    for field in _FIELDS[message_type]:
        if field not in message:
            continue
        value = message[field]
        if field in int_fields and (type(value) not in (int, _Integer) or isinstance(value, _Float)):
            raise ControlProtocolError("INVALID_FIELD_TYPE", f"$.{field}")
        if field == "retryable" and type(value) is not bool:
            raise ControlProtocolError("INVALID_FIELD_TYPE", "$.retryable")
        if field in {
            "protocol",
            "type",
            "client_request_id",
            "character_id",
            "call_id",
            "state",
            "reason",
            "outcome",
            "end_reason",
            "audio_route",
            "response_id",
            "encoding",
            "code",
            "message",
            "request_type",
        } and not isinstance(value, str):
            raise ControlProtocolError("INVALID_FIELD_TYPE", f"$.{field}")
        if field in {"audio", "retire_server_seq"} and not isinstance(value, dict):
            raise ControlProtocolError("INVALID_FIELD_TYPE", f"$.{field}")
    if "audio" in message:
        _validate_object(message["audio"], "$.audio", ("encoding", "sample_rate", "channels"))
    if "retire_server_seq" in message:
        _validate_object(message["retire_server_seq"], "$.retire_server_seq", ("from", "through"))


def _validate_object(value: object, path: str, fields: tuple[str, ...]) -> None:
    if not isinstance(value, dict):
        raise ControlProtocolError("INVALID_FIELD_TYPE", path)
    for field in fields:
        if field not in value:
            raise ControlProtocolError("MISSING_FIELD", f"{path}.{field}")
    for field in value:
        if field not in fields:
            raise ControlProtocolError("UNKNOWN_FIELD", f"{path}.{field}")
    for field in fields:
        item = value[field]
        if field == "encoding" and not isinstance(item, str):
            raise ControlProtocolError("INVALID_FIELD_TYPE", f"{path}.{field}")
        if field != "encoding" and type(item) not in (int, _Integer):
            raise ControlProtocolError("INVALID_FIELD_TYPE", f"{path}.{field}")


def _validate_ranges_and_values(message: dict[str, object], message_type: str) -> None:
    _validate_integer_fields(message)
    _validate_string_fields(message)
    _validate_nested_ranges(message)


def _validate_integer_fields(message: dict[str, object]) -> None:
    seq_fields = {"seq", "stream_id", "missing_seq", "request_seq", "stop_seq"}
    cursor_fields = {"ack_seq", "last_contiguous_server_seq", "last_contiguous_client_seq"}
    for field in seq_fields | cursor_fields:
        if field in message:
            _validate_integer(message[field], f"$.{field}", 1 if field in seq_fields else 0, _UINT32_MAX)
    for field in {"connected_at_ms", "active_duration_ms"}:
        if field in message:
            _validate_integer(message[field], f"$.{field}", 0, _SAFE_INTEGER_MAX)


def _validate_string_fields(message: dict[str, object]) -> None:
    for field in ("client_request_id", "response_id"):
        if field in message:
            _validate_string(message[field], f"$.{field}", 1, 128)
    if "character_id" in message:
        _validate_string(message["character_id"], "$.character_id", 1, 64)
    if "message" in message:
        _validate_string(message["message"], "$.message", 1, 512)
    if "request_type" in message:
        _validate_string(message["request_type"], "$.request_type", 1, 64)
    if "call_id" in message:
        _validate_string(message["call_id"], "$.call_id", 1, None)
        if not _CALL_ID.fullmatch(message["call_id"]):
            raise ControlProtocolError("INVALID_FIELD_VALUE", "$.call_id")
    if "code" in message:
        _validate_string(message["code"], "$.code", 1, 64)
        if not _ERROR_CODE.fullmatch(message["code"]):
            raise ControlProtocolError("INVALID_FIELD_VALUE", "$.code")


def _validate_nested_ranges(message: dict[str, object]) -> None:
    if "audio" in message:
        audio = message["audio"]
        assert isinstance(audio, dict)
        _validate_integer(audio["sample_rate"], "$.audio.sample_rate", 0, _UINT32_MAX)
        _validate_integer(audio["channels"], "$.audio.channels", 0, _UINT32_MAX)
    if "retire_server_seq" in message:
        retired = message["retire_server_seq"]
        assert isinstance(retired, dict)
        _validate_integer(retired["from"], "$.retire_server_seq.from", 1, _UINT32_MAX)
        _validate_integer(retired["through"], "$.retire_server_seq.through", 1, _UINT32_MAX)


def _validate_integer(value: object, path: str, minimum: int, maximum: int) -> None:
    if isinstance(value, _Integer) and value.lexeme == "-0":
        raise ControlProtocolError("INVALID_FIELD_VALUE", path)
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ControlProtocolError("FIELD_OUT_OF_RANGE", path)


def _validate_string(value: object, path: str, minimum: int, maximum: int | None) -> None:
    assert isinstance(value, str)
    if len(value) < minimum or (maximum is not None and len(value) > maximum):
        raise ControlProtocolError("FIELD_OUT_OF_RANGE", path)
    if "\x00" in value or "\ufffd" in value:
        raise ControlProtocolError("INVALID_FIELD_VALUE", path)


def _validate_enums(message: dict[str, object], message_type: str) -> None:
    for field, allowed in _ENUMS.items():
        if field in message and message[field] not in allowed:
            raise ControlProtocolError("INVALID_ENUM", f"$.{field}")
    if message_type == "call.hangup" and message["reason"] not in {"user_hangup", "backgrounded"}:
        raise ControlProtocolError("INVALID_ENUM", "$.reason")
    if message_type == "playback.stop" and message["reason"] != "user_interrupted":
        raise ControlProtocolError("INVALID_ENUM", "$.reason")
    _validate_audio_enums(message, message_type)


def _validate_audio_enums(message: dict[str, object], message_type: str) -> None:
    if "audio" in message:
        audio = message["audio"]
        assert isinstance(audio, dict)
        if audio["encoding"] != "pcm_s16le":
            raise ControlProtocolError("INVALID_ENUM", "$.audio.encoding")
        if audio["sample_rate"] != 16000:
            raise ControlProtocolError("INVALID_ENUM", "$.audio.sample_rate")
        if audio["channels"] != 1:
            raise ControlProtocolError("INVALID_ENUM", "$.audio.channels")
    if message_type == "audio.stream_started":
        if message["sample_rate"] != 24000:
            raise ControlProtocolError("INVALID_ENUM", "$.sample_rate")
        if message["channels"] != 1:
            raise ControlProtocolError("INVALID_ENUM", "$.channels")


def _validate_cross_fields(message: dict[str, object], message_type: str) -> None:
    if message_type == "playback.stop":
        retired = message["retire_server_seq"]
        assert isinstance(retired, dict)
        if retired["from"] > retired["through"]:
            raise ControlProtocolError("INVALID_FIELD_VALUE", "$.retire_server_seq")
        if retired["through"] >= message["seq"]:
            raise ControlProtocolError("INVALID_FIELD_VALUE", "$.retire_server_seq.through")
