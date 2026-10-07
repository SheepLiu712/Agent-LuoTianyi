from types import SimpleNamespace

from src.application.user.user_reset import UserResetService


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
        conversation_service=SimpleNamespace(
            reset_user_conversations=lambda user_id: calls.append(("sql", user_id)) or 2
        ),
        vector_store=SimpleNamespace(delete_user_records=lambda user_id: calls.append(("vector", user_id)) or 1),
        redis_buffer=SimpleNamespace(clear_user=lambda user_id: calls.append(("cache", user_id))),
        media_store=media_store,
    )

    first = service.reset("user")
    assert first.success is False
    assert first.failed_steps == ("media",)

    media_store.fail = False
    second = service.reset("user")
    assert second.success is True
    assert calls == [
        ("sql", "user"),
        ("vector", "user"),
        ("cache", "user"),
        ("sql", "user"),
        ("vector", "user"),
        ("cache", "user"),
    ]
