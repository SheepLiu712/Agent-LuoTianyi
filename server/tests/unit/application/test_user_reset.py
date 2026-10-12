import asyncio
from types import SimpleNamespace

from src.application.user.user_reset import UserResetService


class _Interactions:
    async def begin_user_data_reset(self, user_id):
        return object()

    async def stop_user_interactions(self, user_id):
        return 1

    async def wait_user_settlements(self, user_id):
        return None

    async def end_user_data_reset(self, user_id, token):
        return None


class _MediaStore:
    def __init__(self):
        self.fail = True

    def delete_owned_by(self, *, owner_user_id):
        assert owner_user_id == "user"
        if self.fail:
            raise OSError("busy")
        return SimpleNamespace(deleted_count=0, failures=())


def test_reset_reports_partial_failure_and_is_retry_safe():
    calls = []
    media_store = _MediaStore()
    service = UserResetService(
        interactions=_Interactions(),
        conversation_service=SimpleNamespace(
            reset_user_conversations=lambda user_id: calls.append(("sql", user_id)) or 2
        ),
        memory_store=SimpleNamespace(delete_user_memory_records=lambda user_id: 0),
        user_store=SimpleNamespace(reset_user_profile=lambda user_id: 1),
        vector_store=SimpleNamespace(delete_user_records_strict=lambda user_id: calls.append(("vector", user_id)) or 1),
        redis_buffer=SimpleNamespace(clear_user=lambda user_id: calls.append(("cache", user_id))),
        media_store=media_store,
        call_sessions=SimpleNamespace(delete_by_user=lambda user_id: 0),
        call_maintenance_batches=SimpleNamespace(delete_by_user=lambda user_id: 0),
    )

    first = asyncio.run(service.reset("user"))
    assert first.success is False
    assert first.failed_steps == ("media",)

    media_store.fail = False
    second = asyncio.run(service.reset("user"))
    assert second.success is True
    assert calls == [
        ("vector", "user"),
        ("sql", "user"),
        ("cache", "user"),
        ("vector", "user"),
        ("sql", "user"),
        ("cache", "user"),
    ]
