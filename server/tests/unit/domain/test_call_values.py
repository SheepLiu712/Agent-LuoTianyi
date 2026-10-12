from dataclasses import fields
from uuid import UUID, uuid4

import pytest

from src.domain.call import (
    AckStyle,
    CallAudioSemantic,
    CallContent,
    CallEndReason,
    CallOutcome,
    CallRecallDecision,
    RecallMode,
    derive_call_conversation_id,
)


@pytest.mark.parametrize(
    ("semantic", "expected"),
    [
        (
            CallAudioSemantic(transcript="你好", emotion="开心", sound_description="背景有雨声"),
            "用户带着开心的情绪说：“你好”；背景有雨声",
        ),
        (CallAudioSemantic(transcript="你好", sound_description="背景有雨声"), "用户说：“你好”；背景有雨声"),
        (CallAudioSemantic(transcript="你好", emotion="开心"), "用户带着开心的情绪说：“你好”"),
        (CallAudioSemantic(transcript="你好"), "用户说：“你好”"),
        (CallAudioSemantic(emotion="紧张", sound_description="一声叹息"), "一声叹息；情绪：紧张"),
        (CallAudioSemantic(sound_description="一声叹息"), "一声叹息"),
    ],
)
def test_call_audio_semantic_renders_spec_table(semantic, expected):
    assert semantic.render() == expected


def test_call_audio_semantic_accepts_emotion_only():
    assert CallAudioSemantic(emotion="开心").render() == "情绪：开心"


def test_recall_decision_enforces_mode_contract():
    direct = CallRecallDecision(RecallMode.DIRECT, (), AckStyle.NONE)
    recall = CallRecallDecision(RecallMode.RECALL, ("用户喜欢的歌",), AckStyle.THINKING)

    assert direct.memory_queries == ()
    assert recall.memory_queries == ("用户喜欢的歌",)
    with pytest.raises(ValueError):
        CallRecallDecision(RecallMode.DIRECT, ("query",), AckStyle.NONE)
    with pytest.raises(ValueError):
        CallRecallDecision(RecallMode.RECALL, (), AckStyle.THINKING)
    with pytest.raises(ValueError):
        CallRecallDecision(RecallMode.RECALL, ("query",), AckStyle.NONE)


def test_call_content_has_only_privacy_allowlisted_fields_and_separate_renderings():
    content = CallContent(
        call_id=uuid4(),
        outcome=CallOutcome.CONNECTED,
        active_duration_ms=323_999,
        summary="讨论了演唱会安排",
        end_reason=CallEndReason.USER_HANGUP,
    )

    assert {item.name for item in fields(CallContent)} == {
        "call_id",
        "outcome",
        "active_duration_ms",
        "summary",
        "end_reason",
        "text",
    }
    assert content.text == "[语音通话]讨论了演唱会安排"
    assert content.render_for_history() == "[语音通话] 05:23"
    assert "演唱会" not in content.render_for_history()


@pytest.mark.parametrize(
    ("outcome", "reason", "expected"),
    [
        (CallOutcome.CANCELLED_BEFORE_ANSWER, CallEndReason.USER_HANGUP, "[语音通话] 已取消"),
        (CallOutcome.DECLINED, CallEndReason.DECLINED, "[语音通话] 未接听"),
    ],
)
def test_call_content_renders_calls_that_never_connected(outcome, reason, expected):
    content = CallContent(uuid4(), outcome, 0, None, reason)
    assert content.text == expected
    assert content.render_for_history() == expected


def test_call_conversation_id_is_stable_and_uses_project_namespace():
    call_id = UUID("606ec5e6-a330-4e6c-b07a-8432a5716c8f")

    first = derive_call_conversation_id(user_id="user", character_id="luotianyi", call_id=call_id)
    repeated = derive_call_conversation_id(user_id="user", character_id="luotianyi", call_id=call_id)
    other_owner = derive_call_conversation_id(user_id="other", character_id="luotianyi", call_id=call_id)

    assert first == repeated
    assert first.version == 5
    assert first != other_owner
    assert str(first) == "49988d5c-229c-5f22-be70-9a4ac112d773"
