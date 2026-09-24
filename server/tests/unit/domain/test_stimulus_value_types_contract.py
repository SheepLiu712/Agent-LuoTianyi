from dataclasses import FrozenInstanceError

import pytest

import src.domain.agent as agent_domain


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

VALUE_FIRST_FIELDS = {
    "MediaRef": "media_id",
    "EvidenceRef": "evidence_id",
    "SourceRef": "source_id",
    "BodyRegion": "value",
    "ProactiveReason": "value",
    "WorldObservationKind": "value",
    "ActorRef": "actor_id",
    "TouchClickFrequency": "count_10s",
    "DynamicMessage": "message_id",
    "WorldFact": "fact_id",
    "ActivityFact": "fact_id",
    "SongKnowledgeCandidate": "song_name",
}


def _actor():
    return agent_domain.ActorRef(actor_id="actor-1", display_name="用户甲")


def _candidate():
    return agent_domain.SongKnowledgeCandidate(
        song_name="测试歌曲",
        uploader="投稿者",
        singers=("洛天依",),
        introduction="一首用于契约测试的歌曲。",
        lyrics="测试歌词",
        lyric_keywords=("测试歌词",),
    )


def _dynamic_message():
    return agent_domain.DynamicMessage(
        message_id="dynamic-1",
        parent_message_id=None,
        author_ref=_actor(),
        text="原动态",
        media_refs=(agent_domain.MediaRef(media_id="media-image-1"),),
    )


def _valid_value(type_name: str):
    factories = {
        "MediaRef": lambda: agent_domain.MediaRef(media_id="media-1"),
        "EvidenceRef": lambda: agent_domain.EvidenceRef(evidence_id="evidence-1"),
        "SourceRef": lambda: agent_domain.SourceRef(source_id="source-1"),
        "BodyRegion": lambda: agent_domain.BodyRegion(value="未来新增部位"),
        "ProactiveReason": lambda: agent_domain.ProactiveReason(value="future_reason"),
        "WorldObservationKind": lambda: agent_domain.WorldObservationKind(value="future_fact"),
        "ActorRef": _actor,
        "TouchClickFrequency": lambda: agent_domain.TouchClickFrequency(
            count_10s=2,
            count_30s=5,
        ),
        "DynamicMessage": _dynamic_message,
        "WorldFact": lambda: agent_domain.WorldFact(fact_id="fact-1", summary="事实"),
        "ActivityFact": lambda: agent_domain.ActivityFact(fact_id="fact-1", summary="观察"),
        "SongKnowledgeCandidate": _candidate,
    }
    return factories[type_name]()


def _assert_invalid(factory, /, **kwargs: object) -> None:
    with pytest.raises(agent_domain.InvalidStimulusError) as captured:
        factory(**kwargs)

    assert captured.value.code == "CONTRACT_INVALID_STIMULUS"
    assert captured.value.retryable is False


@pytest.mark.parametrize("type_name", VALUE_TYPES)
def test_value_type_is_publicly_constructible_and_immutable(type_name: str) -> None:
    value = _valid_value(type_name)

    assert isinstance(value, getattr(agent_domain, type_name))
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        setattr(value, VALUE_FIRST_FIELDS[type_name], "changed")


@pytest.mark.parametrize(
    ("type_name", "field_name"),
    [
        ("MediaRef", "media_id"),
        ("EvidenceRef", "evidence_id"),
        ("SourceRef", "source_id"),
        ("BodyRegion", "value"),
        ("ProactiveReason", "value"),
        ("WorldObservationKind", "value"),
    ],
)
def test_single_string_value_type_rejects_blank_values(
    type_name: str,
    field_name: str,
) -> None:
    _assert_invalid(getattr(agent_domain, type_name), **{field_name: " \t"})


@pytest.mark.parametrize(
    ("count_10s", "count_30s"),
    [(-1, 1), (1, -1), (2, 1), (True, 1), (1, False)],
)
def test_touch_click_frequency_rejects_invalid_window_counts(
    count_10s: object,
    count_30s: object,
) -> None:
    _assert_invalid(
        agent_domain.TouchClickFrequency,
        count_10s=count_10s,
        count_30s=count_30s,
    )


def test_dynamic_message_requires_text_or_media() -> None:
    _assert_invalid(
        agent_domain.DynamicMessage,
        message_id="message-1",
        parent_message_id=None,
        author_ref=_actor(),
        text=" \t",
        media_refs=(),
    )
