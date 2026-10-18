"""Identity and liveness needed by interaction admission, independent of transport."""

from typing import Protocol


class InteractionConnection(Protocol):
    @property
    def user_uuid(self) -> str: ...

    @property
    def is_closed(self) -> bool: ...
