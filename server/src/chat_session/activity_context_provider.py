from __future__ import annotations


class ActivityContextProvider:
    """Temporary placeholder for future activity context injection."""

    def get_context_for_runtime(self, user_id: str | None = None) -> str:
        _ = user_id
        return ""
