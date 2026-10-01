from types import SimpleNamespace

import pytest

from src.application.user.user_conversation_helper import UserConversationHelper
from src.domain.conversation_type import ConversationItem


class _ConversationService:
    def get_total_conversation_count(self, user_id):
        assert user_id == "user"
        return 1

    def get_history_from_db(self, user_id, start, end):
        assert (user_id, start, end) == ("user", 0, 1)
        return [
            ConversationItem(
                uuid="image-entry",
                timestamp="2026-09-20 12:00:00",
                source="user",
                type="image",
                content="[图片理解]: [一张图片]:一只白猫",
                data={"media_id": "media", "mime_type": "image/png"},
            )
        ]


@pytest.mark.asyncio
async def test_image_history_hides_agent_description_and_keeps_one_image_item():
    database = SimpleNamespace(conversation_service=_ConversationService())

    result = await UserConversationHelper(database).handle_history_request("user", 10, -1)

    assert result == {
        "history": [
            {
                "uuid": "image-entry",
                "content": "",
                "source": "user",
                "timestamp": "2026-09-20 12:00:00",
                "type": "image",
            }
        ],
        "start_index": 0,
    }


@pytest.mark.asyncio
async def test_audio_history_hides_understanding_metadata_and_reports_availability():
    item = ConversationItem(
        uuid="audio-entry",
        timestamp="2026-09-20 12:00:00",
        source="user",
        type="audio",
        content="[音频]用户说：不应公开",
        data={"media_id": "media", "duration_ms": 15320, "transcript": "不应公开"},
    )
    service = SimpleNamespace(
        get_total_conversation_count=lambda _user_id: 1,
        get_history_from_db=lambda *_args: [item],
    )
    resolver = SimpleNamespace(resolve=lambda *_args, **_kwargs: SimpleNamespace(data=b"audio"))

    result = await UserConversationHelper(
        SimpleNamespace(conversation_service=service), resolver
    ).handle_history_request("user", 10, -1)

    assert result["history"] == [
        {
            "uuid": "audio-entry",
            "content": "[语音消息]",
            "source": "user",
            "timestamp": "2026-09-20 12:00:00",
            "type": "audio",
            "duration_ms": 15320,
            "audio_available": True,
        }
    ]
