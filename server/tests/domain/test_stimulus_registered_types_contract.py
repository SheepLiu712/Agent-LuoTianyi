from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone
from inspect import Parameter, signature
from typing import get_args
from zoneinfo import ZoneInfo

import pytest

import src.domain.agent as agent_domain


OCCURRED_AT = datetime(2026, 9, 5, 9, 30, tzinfo=timezone.utc)
SHANGHAI = ZoneInfo("Asia/Shanghai")

CONSTRUCTIBLE_STIMULI = (
    ("TextMessage", "TEXT_MESSAGE"),
    ("ImageMessage", "IMAGE_MESSAGE"),
    ("VoiceMessage", "VOICE_MESSAGE"),
    ("UserTyping", "USER_TYPING"),
    ("ImageSelectionOpened", "IMAGE_SELECTION_OPENED"),
    ("ImageSelectionClosed", "IMAGE_SELECTION_CLOSED"),
    ("TouchInteraction", "TOUCH_INTERACTION"),
    ("ProactivePromptDue", "PROACTIVE_PROMPT_DUE"),
    ("InteractionDeadline", "INTERACTION_DEADLINE"),
    ("DynamicObserved", "DYNAMIC_OBSERVED"),
    ("DiaryPlanningDue", "DIARY_PLANNING_DUE"),
    ("WorldObservation", "WORLD_OBSERVATION"),
    ("ActivityObservation", "ACTIVITY_OBSERVATION"),
    ("SongKnowledgeDiscovered", "SONG_KNOWLEDGE_DISCOVERED"),
    ("SongLearned", "SONG_LEARNED"),
)

UNAVAILABLE_STIMULI = (
    ("ToyVibration", "TOY_VIBRATION"),
    ("DeviceConnected", "DEVICE_CONNECTED"),
    ("DeviceDisconnected", "DEVICE_DISCONNECTED"),
    ("DailyPlanningDue", "DAILY_PLANNING_DUE"),
    ("ActivityDue", "ACTIVITY_DUE"),
    ("ActivityStarted", "ACTIVITY_STARTED"),
    ("ActivityEnded", "ACTIVITY_ENDED"),
)

VALUE_TYPES = (
    "MediaRef",
    "EvidenceRef",
    "SourceRef",
    "BodyRegion",
    "ProactiveReason",
    "WorldObservationKind",
    "ActorRef",
    "TouchClickFrequency",
    "DynamicMessage",
    "WorldFact",
    "ActivityFact",
    "SongKnowledgeCandidate",
)

def _common_kwargs(type_name: str, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "stimulus_id": f"stimulus-{type_name}",
        "schema_version": 1,
        "occurred_at": OCCURRED_AT,
        "source": agent_domain.StimulusSource.USER,
        "target_character_ids": ("luotianyi",),
        "user_id": "user-1",
        "ephemeral": False,
    }
    values.update(overrides)
    return values


def _actor(actor_id: str = "actor-1"):
    return agent_domain.ActorRef(actor_id=actor_id, display_name="用户甲")


def _dynamic_messages():
    root = agent_domain.DynamicMessage(
        message_id="dynamic-1",
        parent_message_id=None,
        author_ref=_actor("author-post"),
        text="原动态",
        media_refs=(agent_domain.MediaRef(media_id="media-image-1"),),
    )
    comment = agent_domain.DynamicMessage(
        message_id="comment-1",
        parent_message_id="dynamic-1",
        author_ref=_actor("author-comment"),
        text="用户评论",
        media_refs=(),
    )
    return root, comment


def _candidate():
    return agent_domain.SongKnowledgeCandidate(
        song_name="测试歌曲",
        uploader="投稿者",
        singers=("洛天依",),
        introduction="一首用于契约测试的歌曲。",
        lyrics="测试歌词",
        lyric_keywords=("测试歌词",),
    )


def _valid_stimulus_kwargs(type_name: str) -> dict[str, object]:
    values = _common_kwargs(type_name)
    specialized = {
        "TextMessage": lambda: {
            "text": "  你好，天依  ",
            "client_msg_id": "client-text-1",
        },
        "ImageMessage": lambda: {
            "media_ref": agent_domain.MediaRef(media_id="media-image-1"),
            "caption": "图片说明",
            "client_msg_id": "client-image-1",
        },
        "VoiceMessage": lambda: {
            "media_ref": agent_domain.MediaRef(media_id="media-audio-1"),
            "transcript": None,
            "client_msg_id": "client-voice-1",
        },
        "UserTyping": lambda: {"text_length": 12},
        "ImageSelectionOpened": lambda: {},
        "ImageSelectionClosed": lambda: {},
        "TouchInteraction": lambda: {
            "body_regions": (
                agent_domain.BodyRegion(value="头"),
                agent_domain.BodyRegion(value="辫子"),
            ),
            "click_frequency": agent_domain.TouchClickFrequency(
                count_10s=2,
                count_30s=4,
            ),
        },
        "ProactivePromptDue": lambda: {
            "reason": agent_domain.ProactiveReason(value="event_reminder"),
            "due_at": OCCURRED_AT,
            "dedup_key": "proactive:event-1:day_of_event",
            "fact_refs": (agent_domain.EvidenceRef(evidence_id="event-1"),),
        },
        "InteractionDeadline": lambda: {},
        "DynamicObserved": lambda: {
            "dynamic_id": "dynamic-1",
            "target_message_id": "comment-1",
            "target_kind": agent_domain.DynamicTargetKind.COMMENT,
            "messages": _dynamic_messages(),
            "revision": 3,
        },
        "DiaryPlanningDue": lambda: {
            "local_date": date(2026, 9, 5),
            "timezone": SHANGHAI,
            "trigger_id": "diary-trigger-1",
        },
        "WorldObservation": lambda: {
            "observation_kind": agent_domain.WorldObservationKind(value="citywalk"),
            "fact": agent_domain.WorldFact(
                fact_id="world-fact-1",
                summary="角色到达了公园。",
            ),
            "evidence_refs": (),
            "world_revision": 7,
        },
        "ActivityObservation": lambda: {
            "activity_id": "activity-1",
            "observation": agent_domain.ActivityFact(
                fact_id="activity-fact-1",
                summary="角色看见了湖面。",
            ),
            "activity_revision": 2,
        },
        "SongKnowledgeDiscovered": lambda: {
            "source_ref": agent_domain.SourceRef(source_id="vcpedia:测试歌曲"),
            "external_song_id": "测试歌曲",
            "revision": 1,
            "candidate": _candidate(),
            "fetched_at": OCCURRED_AT,
        },
        "SongLearned": lambda: {
            "learning_job_id": "learning-job-1",
            "song_id": "song-1",
            "completed_at": OCCURRED_AT,
        },
    }
    values.update(specialized[type_name]())
    return values


def _assert_invalid(factory, /, **kwargs: object) -> None:
    with pytest.raises(agent_domain.InvalidStimulusError) as captured:
        factory(**kwargs)

    assert captured.value.code == "CONTRACT_INVALID_STIMULUS"
    assert captured.value.retryable is False


def test_agent_domain_exports_the_registered_stimulus_contract() -> None:
    expected_exports = {
        "InvalidStimulusError",
        "Stimulus",
        "StimulusErrorCode",
        "StimulusKind",
        "StimulusSource",
        "DynamicTargetKind",
        *VALUE_TYPES,
        *(name for name, _ in CONSTRUCTIBLE_STIMULI),
        *(name for name, _ in UNAVAILABLE_STIMULI),
    }

    assert expected_exports <= set(agent_domain.__all__)
    assert not hasattr(agent_domain, "PersistPolicy")
    assert set(get_args(agent_domain.StimulusErrorCode)) == {
        "CONTRACT_INVALID_STIMULUS",
        "CONTRACT_UNSUPPORTED_SCHEMA",
        "CONTRACT_STIMULUS_UNAVAILABLE",
    }
    assert {item.name: item.value for item in agent_domain.StimulusKind} == {
        "TEXT_MESSAGE": "text_message",
        "IMAGE_MESSAGE": "image_message",
        "VOICE_MESSAGE": "voice_message",
        "USER_TYPING": "user_typing",
        "IMAGE_SELECTION_OPENED": "image_selection_opened",
        "IMAGE_SELECTION_CLOSED": "image_selection_closed",
        "TOUCH_INTERACTION": "touch_interaction",
        "TOY_VIBRATION": "toy_vibration",
        "DEVICE_CONNECTED": "device_connected",
        "DEVICE_DISCONNECTED": "device_disconnected",
        "PROACTIVE_PROMPT_DUE": "proactive_prompt_due",
        "INTERACTION_DEADLINE": "interaction_deadline",
        "DYNAMIC_OBSERVED": "dynamic_observed",
        "DIARY_PLANNING_DUE": "diary_planning_due",
        "WORLD_OBSERVATION": "world_observation",
        "DAILY_PLANNING_DUE": "daily_planning_due",
        "ACTIVITY_DUE": "activity_due",
        "ACTIVITY_STARTED": "activity_started",
        "ACTIVITY_OBSERVATION": "activity_observation",
        "ACTIVITY_ENDED": "activity_ended",
        "SONG_KNOWLEDGE_DISCOVERED": "song_knowledge_discovered",
        "SONG_LEARNED": "song_learned",
    }
    assert {item.name: item.value for item in agent_domain.DynamicTargetKind} == {
        "POST": "post",
        "COMMENT": "comment",
    }


@pytest.mark.parametrize(("type_name", "kind_name"), CONSTRUCTIBLE_STIMULI)
def test_constructible_stimulus_preserves_fields_and_fixed_kind(
    type_name: str,
    kind_name: str,
) -> None:
    stimulus_type = getattr(agent_domain, type_name)
    values = _valid_stimulus_kwargs(type_name)

    stimulus = stimulus_type(**values)

    assert isinstance(stimulus, agent_domain.Stimulus)
    assert stimulus.kind is getattr(agent_domain.StimulusKind, kind_name)
    for field_name, expected in values.items():
        assert getattr(stimulus, field_name) == expected
    assert not hasattr(stimulus, "payload")
    assert not hasattr(stimulus, "persist_policy")
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        stimulus.stimulus_id = "changed"


@pytest.mark.parametrize(("type_name", "_kind_name"), CONSTRUCTIBLE_STIMULI)
def test_constructible_stimulus_constructor_is_keyword_only(
    type_name: str,
    _kind_name: str,
) -> None:
    parameters = signature(getattr(agent_domain, type_name)).parameters

    for field_name in _valid_stimulus_kwargs(type_name):
        assert parameters[field_name].kind is Parameter.KEYWORD_ONLY
    assert "kind" not in parameters
    assert "payload" not in parameters
    assert "persist_policy" not in parameters


@pytest.mark.parametrize(("type_name", "kind_name"), UNAVAILABLE_STIMULI)
def test_unavailable_stimulus_is_registered_but_cannot_be_constructed(
    type_name: str,
    kind_name: str,
) -> None:
    stimulus_type = getattr(agent_domain, type_name)

    assert issubclass(stimulus_type, agent_domain.Stimulus)
    assert stimulus_type.kind is getattr(agent_domain.StimulusKind, kind_name)
    with pytest.raises(agent_domain.InvalidStimulusError) as captured:
        stimulus_type(unexpected="ignored")

    assert captured.value.code == "CONTRACT_STIMULUS_UNAVAILABLE"
    assert captured.value.retryable is False


@pytest.mark.parametrize(
    ("type_name", "field_name", "wrong_reference"),
    [
        (
            "ImageMessage",
            "media_ref",
            agent_domain.EvidenceRef(evidence_id="evidence-not-media"),
        ),
        (
            "WorldObservation",
            "evidence_refs",
            (agent_domain.MediaRef(media_id="media-not-evidence"),),
        ),
        (
            "SongKnowledgeDiscovered",
            "source_ref",
            agent_domain.MediaRef(media_id="media-not-source"),
        ),
    ],
)
def test_controlled_reference_nominal_types_cannot_be_interchanged(
    type_name: str,
    field_name: str,
    wrong_reference: object,
) -> None:
    values = _valid_stimulus_kwargs(type_name)
    values[field_name] = wrong_reference

    _assert_invalid(getattr(agent_domain, type_name), **values)


@pytest.mark.parametrize(
    ("target_kind", "target_message_id", "messages"),
    [
        ("COMMENT", "missing", "valid"),
        ("POST", "comment-1", "valid"),
        ("COMMENT", "dynamic-1", "valid"),
        ("COMMENT", "comment-1", "duplicate"),
        ("COMMENT", "comment-1", "wrong_root"),
        ("COMMENT", "comment-1", "missing_parent"),
    ],
)
def test_dynamic_observed_rejects_an_invalid_thread_structure(
    target_kind: str,
    target_message_id: str,
    messages: str,
) -> None:
    root, comment = _dynamic_messages()
    variants = {
        "valid": (root, comment),
        "duplicate": (root, comment, comment),
        "wrong_root": (comment, root),
        "missing_parent": (
            root,
            agent_domain.DynamicMessage(
                message_id="comment-1",
                parent_message_id="missing",
                author_ref=_actor(),
                text="评论",
                media_refs=(),
            ),
        ),
    }
    _assert_invalid(
        agent_domain.DynamicObserved,
        **_common_kwargs("DynamicObserved"),
        dynamic_id="dynamic-1",
        target_message_id=target_message_id,
        target_kind=getattr(agent_domain.DynamicTargetKind, target_kind),
        messages=variants[messages],
        revision=1,
    )


@pytest.mark.parametrize(
    ("type_name", "updates"),
    [
        ("ImageMessage", {"caption": " \t"}),
        ("VoiceMessage", {"media_ref": None, "transcript": None}),
        ("UserTyping", {"text_length": -1}),
        ("UserTyping", {"text_length": True}),
        ("TouchInteraction", {"body_regions": ()}),
        ("DiaryPlanningDue", {"local_date": OCCURRED_AT}),
        ("DiaryPlanningDue", {"timezone": timezone.utc}),
        ("WorldObservation", {"world_revision": -1}),
        ("ActivityObservation", {"activity_revision": True}),
        ("SongKnowledgeDiscovered", {"revision": -1}),
    ],
)
def test_constructible_stimulus_rejects_a_specialized_invalid_value(
    type_name: str,
    updates: dict[str, object],
) -> None:
    values = _valid_stimulus_kwargs(type_name)
    values.update(updates)
    _assert_invalid(getattr(agent_domain, type_name), **values)


@pytest.mark.parametrize(
    ("type_name", "removed_field", "removed_value"),
    [
        ("InteractionDeadline", "pending_stimulus_ids", ("stimulus-1",)),
        ("TouchInteraction", "gesture", "tap"),
        ("SongKnowledgeDiscovered", "evidence_refs", ()),
        ("SongLearned", "artifact_refs", ("artifact-1",)),
    ],
)
def test_current_interface_rejects_fields_owned_by_other_or_future_modules(
    type_name: str,
    removed_field: str,
    removed_value: object,
) -> None:
    values = _valid_stimulus_kwargs(type_name)
    values[removed_field] = removed_value

    _assert_invalid(getattr(agent_domain, type_name), **values)


@pytest.mark.parametrize(
    ("type_name", "required_field"),
    [
        ("ImageMessage", "media_ref"),
        ("VoiceMessage", "client_msg_id"),
        ("UserTyping", "text_length"),
        ("TouchInteraction", "body_regions"),
        ("ProactivePromptDue", "reason"),
        ("DynamicObserved", "messages"),
        ("DiaryPlanningDue", "local_date"),
        ("WorldObservation", "fact"),
        ("ActivityObservation", "observation"),
        ("SongKnowledgeDiscovered", "candidate"),
        ("SongLearned", "song_id"),
    ],
)
def test_constructible_stimulus_reports_missing_specialized_field_as_contract_error(
    type_name: str,
    required_field: str,
) -> None:
    values = _valid_stimulus_kwargs(type_name)
    values.pop(required_field)

    _assert_invalid(getattr(agent_domain, type_name), **values)
