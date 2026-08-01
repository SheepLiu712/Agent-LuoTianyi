from src.network.event_types import (
    WSMessage,
    WSEventType,
    is_audio_terminal,
    normalize_agent_message,
)


def test_audio_error_final_package_is_a_terminal_event():
    message = WSMessage(
        event_type=WSEventType.AGENT_MESSAGE,
        payload={
            "uuid": "reply-1",
            "text": "已经生成的文本",
            "audio": "",
            "is_final_package": True,
            "audio_error": True,
            "error_code": "TTS_EMPTY",
        },
    )

    normalized = normalize_agent_message(message)

    assert normalized.text == "已经生成的文本"
    assert normalized.audio_error is True
    assert normalized.error_code == "TTS_EMPTY"
    assert is_audio_terminal(normalized) is True


def test_non_final_audio_error_flag_does_not_end_playback_by_itself():
    message = WSMessage(
        event_type=WSEventType.AGENT_MESSAGE,
        payload={
            "uuid": "reply-1",
            "is_final_package": False,
            "audio_error": True,
            "error_code": "TTS_STREAM_ERROR",
        },
    )

    assert is_audio_terminal(normalize_agent_message(message)) is False
