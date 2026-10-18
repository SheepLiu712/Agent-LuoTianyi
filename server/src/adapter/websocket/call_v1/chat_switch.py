"""Public call.v1 handshake on the chat channel; no transport/session ownership."""

from ._control import _ControlProtocolError, _decode_control_text


class CallSwitchProtocolError(ValueError):
    """Invalid chat-to-call handshake carrying a stable wire error code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def parse_switch_prepare(raw: str | bytes) -> tuple[str, str]:
    """Validate the original frame and return (character_id, client_request_id).

    Size, sender, route and field validation remain owned by call.v1. This
    operation does not reserve a Stage or change interaction state.
    """
    try:
        message = _decode_control_text(raw, sender="client", transport="chat_ws")
    except _ControlProtocolError as error:
        raise CallSwitchProtocolError(error.code) from None
    if message["type"] != "call.switch_prepare":
        raise CallSwitchProtocolError("UNKNOWN_TYPE")
    return str(message["character_id"]), str(message["client_request_id"])


def make_switch_ready(*, character_id: str, client_request_id: str) -> dict[str, str]:
    """Build the response after StageManager accepts a validated prepare request."""
    return {
        "protocol": "call.v1",
        "type": "call.switch_ready",
        "client_request_id": client_request_id,
        "character_id": character_id,
    }
