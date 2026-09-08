"""按交互记录正在执行的处理是否允许被普通刺激打断。"""
from contextlib import contextmanager
from dataclasses import dataclass
from collections.abc import Iterator


@dataclass(eq=False)
class _CallInterruptibility:
    allowed: bool = False


class _InteractionInterruptibility:
    def __init__(self) -> None:
        self._active: dict[tuple[str, str], set[_CallInterruptibility]] = {}

    def allows(self, interaction_id: str, operation: str) -> bool:
        if not isinstance(interaction_id, str) or not interaction_id.strip():
            raise ValueError("interaction_id must be nonblank")
        calls = self._active.get((interaction_id, operation), ())
        return bool(calls) and all(call.allowed for call in calls)

    @contextmanager
    def track(self, interaction_id: str, operation: str) -> Iterator[_CallInterruptibility]:
        key = (interaction_id, operation)
        state = _CallInterruptibility()
        calls = self._active.setdefault(key, set())
        calls.add(state)
        try:
            yield state
        finally:
            calls.remove(state)
            if not calls:
                del self._active[key]
