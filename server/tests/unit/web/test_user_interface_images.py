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
