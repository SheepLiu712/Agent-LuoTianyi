from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from src.domain.agent import PersistPolicy, StimulusKind, StimulusSource, TextMessage


def test_text_message_constructs_as_immutable_registered_stimulus() -> None:
    occurred_at = datetime(2026, 9, 5, 8, 30, tzinfo=timezone.utc)

    stimulus = TextMessage(
        stimulus_id="stimulus-text-1",
        schema_version=1,
        occurred_at=occurred_at,
        source=StimulusSource.USER,
        target_character_ids=("luotianyi",),
        user_id="user-1",
        persist_policy=PersistPolicy.CONVERSATION_AND_MEMORY_CANDIDATE,
        ephemeral=False,
        text="你好，天依",
        client_msg_id="client-message-1",
    )

    assert stimulus.kind is StimulusKind.TEXT_MESSAGE
    assert stimulus.occurred_at == occurred_at
    assert stimulus.target_character_ids == ("luotianyi",)
    assert stimulus.text == "你好，天依"

    with pytest.raises(FrozenInstanceError):
        stimulus.text = "被修改的内容"
