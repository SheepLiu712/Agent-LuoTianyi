import json

import pytest

from src.adapter.websocket.call_v1.chat_switch import (
    CallSwitchProtocolError,
    make_switch_ready,
    parse_switch_prepare,
)


def _prepare(**changes):
    return json.dumps(
        {
            "protocol": "call.v1",
            "type": "call.switch_prepare",
            "character_id": "luotianyi",
            "client_request_id": "request-1",
            **changes,
        }
    )


@pytest.mark.parametrize("binary", [False, True])
def test_switch_handshake_preserves_identity(binary):
    raw = _prepare()
    character_id, request_id = parse_switch_prepare(raw.encode() if binary else raw)
    assert make_switch_ready(character_id=character_id, client_request_id=request_id) == {
        "protocol": "call.v1",
        "type": "call.switch_ready",
        "character_id": "luotianyi",
        "client_request_id": "request-1",
    }


@pytest.mark.parametrize(
    "raw, code",
    [
        ("{", "BAD_JSON"),
        (_prepare(protocol="unknown"), "UNSUPPORTED_PROTOCOL"),
        (_prepare(type="call.start"), "INVALID_TRANSPORT"),
        (_prepare(type="call.switch_ready"), "INVALID_DIRECTION"),
        (_prepare(character_id=42), "INVALID_FIELD_TYPE"),
        (" " * 17000 + _prepare(), "CONTROL_TOO_LARGE"),
    ],
)
def test_switch_rejects_invalid_original_frames_with_public_errors(raw, code):
    with pytest.raises(CallSwitchProtocolError) as raised:
        parse_switch_prepare(raw)
    assert raised.value.code == code
