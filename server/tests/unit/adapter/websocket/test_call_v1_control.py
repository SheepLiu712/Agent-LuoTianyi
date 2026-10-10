"""Shared-fixture tests for the pure ``call.v1`` control parser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.adapter.websocket.call_v1.control import ControlProtocolError, decode_control_text, encode_control_message

_FIXTURE_PATH = Path(__file__).parents[5] / "contracts" / "call_v1" / "fixtures" / "control_messages.json"
_FIXTURE = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
_SENDER = {"client_to_server": "client", "server_to_client": "server"}


def _invalid_raw(case: dict[str, object]) -> str | bytes:
    if "raw_hex" in case:
        return bytes.fromhex(case["raw_hex"])
    if "raw_pattern" not in case:
        return case["raw"]
    pattern = case["raw_pattern"]
    return pattern["prefix"] + pattern["repeat"] * pattern["count"] + pattern["suffix"]


@pytest.mark.parametrize("case", _FIXTURE["valid"], ids=lambda case: case["id"])
def test_decode_and_encode_valid_shared_messages(case: dict[str, object]) -> None:
    sender = _SENDER[case["direction"]]
    message = decode_control_text(case["raw"], sender=sender, transport=case["transport"])

    assert message == case["message"]
    encoded = encode_control_message(message, sender=sender, transport=case["transport"])
    assert encoded == case["raw"]
    assert decode_control_text(encoded, sender=sender, transport=case["transport"]) == message


@pytest.mark.parametrize("case", _FIXTURE["invalid"], ids=lambda case: case["id"])
def test_decode_rejects_invalid_shared_messages(case: dict[str, object]) -> None:
    with pytest.raises(ControlProtocolError) as raised:
        decode_control_text(_invalid_raw(case), sender=_SENDER[case["direction"]], transport=case["transport"])

    assert raised.value.code == case["expected"]["error"]
    assert raised.value.path == case["expected"]["path"]


def test_encode_rejects_invalid_typed_object() -> None:
    with pytest.raises(ControlProtocolError) as raised:
        encode_control_message(
            {"protocol": "call.v1", "type": "ack", "call_id": "not-a-uuid", "ack_seq": 0},
            sender="client",
            transport="call_ws",
        )

    assert (raised.value.code, raised.value.path) == ("INVALID_FIELD_VALUE", "$.call_id")


def test_encode_canonicalizes_nested_field_order() -> None:
    message = {
        "audio": {"channels": 1, "sample_rate": 16000, "encoding": "pcm_s16le"},
        "character_id": "luotianyi",
        "client_request_id": "request",
        "seq": 1,
        "type": "call.start",
        "protocol": "call.v1",
    }

    assert encode_control_message(message, sender="client", transport="call_ws") == (
        '{"protocol":"call.v1","type":"call.start","seq":1,"client_request_id":"request",'
        '"character_id":"luotianyi","audio":{"encoding":"pcm_s16le","sample_rate":16000,"channels":1}}'
    )


@pytest.mark.parametrize(
    ("value", "code"),
    [("\x00", "INVALID_FIELD_VALUE"), ("\ufffd", "INVALID_FIELD_VALUE"), ("\ud800", "BAD_JSON")],
)
def test_encode_rejects_invalid_unicode(value: str, code: str) -> None:
    with pytest.raises(ControlProtocolError) as raised:
        encode_control_message(
            {"protocol": "call.v1", "type": "error", "code": "BAD_VALUE", "message": value, "retryable": False},
            sender="client",
            transport="call_ws",
        )

    assert (raised.value.code, raised.value.path) == (code, "$.message" if code != "BAD_JSON" else "$")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), -0.0])
def test_encode_rejects_non_integer_numeric_values(value: float) -> None:
    with pytest.raises(ControlProtocolError) as raised:
        encode_control_message(
            {
                "protocol": "call.v1",
                "type": "call.start",
                "seq": value,
                "client_request_id": "request",
                "character_id": "luotianyi",
                "audio": {"encoding": "pcm_s16le", "sample_rate": 16000, "channels": 1},
            },
            sender="client",
            transport="call_ws",
        )

    assert (raised.value.code, raised.value.path) == ("INVALID_FIELD_TYPE", "$.seq")


def test_decode_counts_multibyte_utf8_at_raw_limit() -> None:
    base = '{"protocol":"call.v1","type":"error","code":"OK","message":"界","retryable":false}'
    exact = base + " " * (16_384 - len(base.encode("utf-8")))

    assert decode_control_text(exact, sender="server", transport="call_ws")["type"] == "error"
    with pytest.raises(ControlProtocolError) as raised:
        decode_control_text(exact + " ", sender="server", transport="call_ws")

    assert (raised.value.code, raised.value.path) == ("CONTROL_TOO_LARGE", "$")
