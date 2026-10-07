from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class UserResetStep:
    name: str
    success: bool
    deleted_count: int = 0
    error: str | None = None


@dataclass(frozen=True)
class UserResetReport:
    user_id: str
    steps: tuple[UserResetStep, ...]

    @property
    def success(self) -> bool:
        return all(step.success for step in self.steps)

    @property
    def failed_steps(self) -> tuple[str, ...]:
        return tuple(step.name for step in self.steps if not step.success)


class UserResetService:
    """Best-effort, retry-safe orchestration for deleting all user-owned data."""

    def __init__(self, *, conversation_service, vector_store, redis_buffer, media_store) -> None:
        self._conversation_service = conversation_service
        self._vector_store = vector_store
        self._redis = redis_buffer
        self._media_store = media_store

    def reset(self, user_id: str) -> UserResetReport:
        steps = (
            self._run_count_step("conversations", lambda: self._conversation_service.reset_user_conversations(user_id)),
            self._run_count_step("vectors", lambda: self._vector_store.delete_user_records(user_id)),
            self._run_void_step("cache", lambda: self._redis.clear_user(user_id)),
            self._run_media_step(user_id),
        )
        return UserResetReport(user_id=user_id, steps=steps)

    @staticmethod
    def _run_count_step(name: str, operation: Callable[[], int]) -> UserResetStep:
        try:
            deleted_count = operation()
        except Exception as error:
            return UserResetStep(name=name, success=False, error=type(error).__name__)
        return UserResetStep(name=name, success=True, deleted_count=deleted_count)

    @staticmethod
    def _run_void_step(name: str, operation: Callable[[], None]) -> UserResetStep:
        try:
            operation()
        except Exception as error:
            return UserResetStep(name=name, success=False, error=type(error).__name__)
        return UserResetStep(name=name, success=True)

    def _run_media_step(self, user_id: str) -> UserResetStep:
        try:
            report = self._media_store.delete_owned_by(owner_user_id=user_id)
        except Exception as error:
            return UserResetStep(name="media", success=False, error=type(error).__name__)
        if report.failures:
            return UserResetStep(
                name="media",
                success=False,
                deleted_count=report.deleted_count,
                error=",".join(failure.media_id for failure in report.failures),
            )
        return UserResetStep(name="media", success=True, deleted_count=report.deleted_count)
