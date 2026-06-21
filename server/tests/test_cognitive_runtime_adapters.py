import os
import sys

current_dir = os.getcwd()
if current_dir not in sys.path:
    sys.path.append(current_dir)

from src.domain.memory_record import MemoryRecord, MemoryType, MemoryVisibility
from src.domain.stimulus import PersistPolicy, StimulusModality
from src.system.user_interface.types import WSEventType, WSMessage
from src.system.user_interface.websocket_service import WebSocketService
from src.legacy.chat_input_adapter import stimulus_to_chat_input_event, ws_message_to_stimulus
from src.agent.chat.chat_events import ChatInputEventType
from src.agent.chat.unread_store import UnreadStore
from src.runtime.character_registry import get_default_character_registry


def test_ws_text_message_round_trips_to_legacy_chat_event():
    ws_message = WSMessage(
        event_type=WSEventType.USER_TEXT.value,
        payload={"text": "你好呀", "target_character_id": "luotianyi"},
        client_msg_id="msg-1",
        ts=123,
    )

    stimulus = ws_message_to_stimulus(ws_message, sender_user_id="user-1")
    assert stimulus is not None
    assert stimulus.modality == StimulusModality.TEXT
    assert stimulus.text == "你好呀"
    assert stimulus.sender_user_id == "user-1"
    assert stimulus.target_character_ids == ("luotianyi",)
    assert stimulus.persist_policy == PersistPolicy.CONVERSATION_AND_MEMORY_CANDIDATE

    chat_event = stimulus_to_chat_input_event(stimulus)
    assert chat_event is not None
    assert chat_event.event_type == ChatInputEventType.USER_TEXT
    assert chat_event.text == "你好呀"
    assert chat_event.client_msg_id == "msg-1"
    assert chat_event.ts == 123
    assert chat_event.payload["target_character_ids"] == ["luotianyi"]

    unread = UnreadStore.trans_ChatInputEvent_to_UnreadMessage(chat_event)
    assert unread.target_character_ids == ("luotianyi",)


def test_websocket_service_uses_stimulus_adapter_for_chat_conversion():
    service = WebSocketService()
    ws_message = WSMessage(
        event_type=WSEventType.USER_TEXT.value,
        payload={"message": "从旧协议进来"},
        client_msg_id="msg-2",
    )

    stimulus = service.convert_to_stimulus(ws_message, sender_user_id="user-2")
    assert stimulus is not None
    assert stimulus.text == "从旧协议进来"
    assert stimulus.sender_user_id == "user-2"

    chat_event = service.convert_to_chat_input_event(ws_message, sender_user_id="user-2")
    assert chat_event is not None
    assert chat_event.event_type == ChatInputEventType.USER_TEXT
    assert chat_event.text == "从旧协议进来"


def test_ws_touch_message_is_ephemeral_stimulus_but_legacy_touch_event():
    ws_message = WSMessage(
        event_type=WSEventType.USER_TOUCH.value,
        payload={"touchArea": ["head"], "click_frequency": {"count_10s": 2, "count_30s": 3}},
        client_msg_id="touch-1",
        ts=456,
    )

    stimulus = ws_message_to_stimulus(ws_message, sender_user_id="user-1")
    assert stimulus is not None
    assert stimulus.modality == StimulusModality.TOUCH
    assert stimulus.ephemeral is True
    assert stimulus.persist_policy == PersistPolicy.EPHEMERAL_ONLY
    assert stimulus.text.startswith("[用户摸了摸天依的头")

    chat_event = stimulus_to_chat_input_event(stimulus)
    assert chat_event is not None
    assert chat_event.event_type == ChatInputEventType.USER_TOUCH
    assert chat_event.text == stimulus.text
    assert chat_event.payload["ephemeral"] is True
    assert chat_event.payload["persist_policy"] == PersistPolicy.EPHEMERAL_ONLY.value


def test_default_character_registry_exposes_luotianyi_profile():
    registry = get_default_character_registry()
    profile = registry.get()

    assert profile.character_id == "luotianyi"
    assert profile.default_target is True
    assert registry.resolve_targets(None) == ("luotianyi",)


def test_memory_record_is_canonical_memory_entity():
    record = MemoryRecord(
        owner_character_id="luotianyi",
        subject_user_id="user-1",
        memory_type=MemoryType.USER_FACT,
        visibility=MemoryVisibility.PRIVATE,
        source="chat",
        content="用户喜欢蓝色。",
    )

    assert record.id
    assert record.owner_character_id == "luotianyi"
    assert record.memory_type == MemoryType.USER_FACT
    assert record.visibility == MemoryVisibility.PRIVATE
    assert record.content == "用户喜欢蓝色。"
