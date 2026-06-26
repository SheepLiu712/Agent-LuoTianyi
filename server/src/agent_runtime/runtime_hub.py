from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session


class AgentRuntimeHub:
    """Runtime services made available to character agents.

    The hub keeps long-lived infrastructure out of the conscious agent API while
    preserving the legacy agent's need to access storage and capabilities during
    the migration.
    """

    def __init__(
        self,
        config: dict[str, Any],
        *,
        redis_client: Any,
        vector_store: Any,
        sql_session_factory: Callable[[], Session],
        database: Any,
        music_manager: Any,
        capabilities: Any | None = None,
    ) -> None:
        self.config = config
        self.redis_client = redis_client
        self.vector_store = vector_store
        self.sql_session_factory = sql_session_factory
        self.database = database
        self.music_manager = music_manager
        self.capabilities = capabilities

    def open_sql_session(self) -> Session:
        return self.sql_session_factory()
