from types import SimpleNamespace

import pytest

from src.infrastructure.media import ResolvedMedia
from src.web.http.user_interface import UserInterface


class _CredentialService:
    @staticmethod
    def check_message_token(username, token):
        assert (username, token) == ("name", "token")
        return True, "user"


class _ConversationService:
    @staticmethod
    def get_image_media_id(user_id, entry_id):
        assert (user_id, entry_id) == ("user", "entry")
        return "media"

    @staticmethod
    def get_image_server_path(*_args):
        raise AssertionError("permanent media must be preferred over a legacy path")


class _MediaResolver:
    @staticmethod
    def resolve(media_ref, *, owner_user_id):
        assert media_ref.media_id == "media"
        assert owner_user_id == "user"
        return ResolvedMedia(data=b"image", mime_type="image/png")


@pytest.mark.asyncio
async def test_get_image_resolves_permanent_media_from_single_conversation_entry():
    database = SimpleNamespace(
        credential_service=_CredentialService(),
        conversation_service=_ConversationService(),
    )
    runtime = SimpleNamespace(database_manager=database, media_resolver=_MediaResolver())
    request = SimpleNamespace(username="name", token="token", uuid="entry")

    response = await UserInterface(database).get_image(request, runtime)

    assert response.media_type == "image/png"
    assert b"".join([chunk async for chunk in response.body_iterator]) == b"image"


@pytest.mark.asyncio
async def test_get_audio_authenticates_owner_and_streams_mp4():
    credential = SimpleNamespace(authenticate_message_token=lambda token: "user" if token == "token" else None)
    conversation = SimpleNamespace(get_audio_media_id=lambda user_id, entry_id: "media")

    def resolve(media_ref, *, owner_user_id, expected_kind):
        assert (media_ref.media_id, owner_user_id, expected_kind) == ("media", "user", "audio")
        return ResolvedMedia(data=b"audio", mime_type="audio/mp4")

    database = SimpleNamespace(credential_service=credential, conversation_service=conversation)
    runtime = SimpleNamespace(database_manager=database, media_resolver=SimpleNamespace(resolve=resolve))

    response = await UserInterface(database).get_audio("token", "entry", runtime)

    assert response.media_type == "audio/mp4"
    assert response.headers["content-length"] == "5"
    assert b"".join([chunk async for chunk in response.body_iterator]) == b"audio"


@pytest.mark.asyncio
async def test_get_audio_unknown_or_other_owner_is_not_disclosed():
    database = SimpleNamespace(
        credential_service=SimpleNamespace(authenticate_message_token=lambda _token: "user"),
        conversation_service=SimpleNamespace(get_audio_media_id=lambda *_args: None),
    )
    runtime = SimpleNamespace(database_manager=database, media_resolver=SimpleNamespace())

    with pytest.raises(Exception) as error:
        await UserInterface(database).get_audio("token", "entry", runtime)

    assert error.value.status_code == 404


def test_wire_dependencies_injects_media_resolver_into_history_helper():
    """生产接线必须把 media_resolver 交给历史读取用的 helper。

    历史上靠 get_history 里逐请求改写 helper 的共享状态补洞；若日后有人删掉那行而接线又漏传，
    历史里所有音频的 audio_available 会静默变 False。
    """
    database = SimpleNamespace()
    resolver = _MediaResolver()
    user_interface = UserInterface(database)

    user_interface.wire_dependencies(database_manager=database, media_resolver=resolver)

    assert user_interface.media_resolver is resolver
    assert user_interface.user_conversation_helper.media_resolver is resolver
