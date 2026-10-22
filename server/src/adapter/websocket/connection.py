"""The network contract shared by chat and call adapters."""

from dataclasses import dataclass


class AdapterConnectionError(ValueError):
    """Adapter rejection with optional encoded response before closing a socket."""

    def __init__(self, code: str, *, close_code: int = 1002, initial_message: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.close_code = close_code
        self.initial_message = initial_message


class AdapterConnection:
    """Opaque identity of one attachment, never a Stage or a physical socket."""

    __slots__ = ("_token",)

    def __init__(self) -> None:
        self._token = object()


@dataclass(frozen=True, slots=True)
class OutboundDelivery:
    """One network attempt. Protocol sequence numbers live inside message."""

    delivery_id: str
    message: str | bytes
