from datetime import datetime, timezone

import pytest

from src.domain.agent import StimulusKind, StimulusSource, TextMessage


def test_text_message_constructs_as_immutable_registered_stimulus() -> None:
    occurred_at = datetime(2026, 9, 5, 8, 30, tzinfo=timezone.utc)

    stimulus = TextMessage(
        stimulus_id="stimulus-text-1",
        schema_version=1,
        occurred_at=occurred_at,
        source=StimulusSource.USER,
        target_character_ids=("luotianyi",),
        user_id="user-1",
        ephemeral=False,
        text="你好，天依",
        client_msg_id="client-message-1",
    )

    assert stimulus.kind is StimulusKind.TEXT_MESSAGE
    assert stimulus.stimulus_id == "stimulus-text-1"
    assert stimulus.schema_version == 1
    assert stimulus.occurred_at == occurred_at
    assert stimulus.source is StimulusSource.USER
    assert stimulus.target_character_ids == ("luotianyi",)
    assert stimulus.user_id == "user-1"
    assert not hasattr(stimulus, "persist_policy")
    assert stimulus.ephemeral is False
    assert stimulus.text == "你好，天依"
    assert stimulus.client_msg_id == "client-message-1"
    assert not hasattr(stimulus, "payload")

    with pytest.raises((AttributeError, TypeError, ValueError)):
        stimulus.text = "被修改的内容"
    assert stimulus.text == "你好，天依"
