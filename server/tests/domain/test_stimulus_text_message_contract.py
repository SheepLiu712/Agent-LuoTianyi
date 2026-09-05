from datetime import datetime, timezone
from inspect import Parameter, isabstract, signature
from typing import get_args

import pytest

import src.domain.agent as agent_domain


OCCURRED_AT = datetime(2026, 9, 5, 8, 30, tzinfo=timezone.utc)


def _valid_message_kwargs(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "stimulus_id": "stimulus-text-1",
        "schema_version": 1,
        "occurred_at": OCCURRED_AT,
        "source": agent_domain.StimulusSource.USER,
        "target_character_ids": ("luotianyi", "yuezhengling"),
        "user_id": "user-1",
        "ephemeral": False,
        "text": "  你好，天依  ",
        "client_msg_id": "client-message-1",
    }
    values.update(overrides)
    return values


def _assert_invalid_stimulus(
    expected_code: str,
    *,
    omitted_field: str | None = None,
    **overrides: object,
) -> None:
    values = _valid_message_kwargs(**overrides)
    if omitted_field is not None:
        values.pop(omitted_field)

    with pytest.raises(agent_domain.InvalidStimulusError) as captured:
        agent_domain.TextMessage(**values)

    assert isinstance(captured.value, ValueError)
    assert captured.value.code == expected_code
    assert captured.value.retryable is False


def test_agent_domain_exports_registered_contract_without_persistence_policy() -> None:
    expected_exports = {
        "InvalidStimulusError",
        "Stimulus",
        "StimulusErrorCode",
        "StimulusKind",
        "StimulusSource",
        "TextMessage",
    }

    assert expected_exports <= set(agent_domain.__all__)
    assert not hasattr(agent_domain, "PersistPolicy")
    assert set(get_args(agent_domain.StimulusErrorCode)) == {
        "CONTRACT_INVALID_STIMULUS",
        "CONTRACT_UNSUPPORTED_SCHEMA",
    }
    assert {item.name: item.value for item in agent_domain.StimulusKind} == {
        "TEXT_MESSAGE": "text_message",
    }
    assert {item.name: item.value for item in agent_domain.StimulusSource} == {
        "USER": "user",
        "DEVICE": "device",
        "WORLD": "world",
        "STAGE": "stage",
    }


def test_text_message_is_a_concrete_stimulus_but_stimulus_is_abstract() -> None:
    assert isabstract(agent_domain.Stimulus)
    assert issubclass(agent_domain.TextMessage, agent_domain.Stimulus)

    with pytest.raises(TypeError):
        agent_domain.Stimulus(
            stimulus_id="stimulus-base-1",
            schema_version=1,
            occurred_at=OCCURRED_AT,
            source=agent_domain.StimulusSource.USER,
            target_character_ids=("luotianyi",),
            user_id=None,
            ephemeral=False,
        )


def test_text_message_preserves_explicit_fields_and_is_immutable() -> None:
    message = agent_domain.TextMessage(**_valid_message_kwargs())

    assert isinstance(message, agent_domain.Stimulus)
    assert message.kind is agent_domain.StimulusKind.TEXT_MESSAGE
    assert message.stimulus_id == "stimulus-text-1"
    assert message.schema_version == 1
    assert message.occurred_at == OCCURRED_AT
    assert message.source is agent_domain.StimulusSource.USER
    assert message.target_character_ids == ("luotianyi", "yuezhengling")
    assert message.user_id == "user-1"
    assert message.ephemeral is False
    assert message.text == "  你好，天依  "
    assert message.client_msg_id == "client-message-1"
    assert not hasattr(message, "payload")
    assert not hasattr(message, "persist_policy")

    with pytest.raises((AttributeError, TypeError)):
        message.text = "被修改的内容"

    assert message.text == "  你好，天依  "


def test_text_message_accepts_unusual_but_field_valid_combinations() -> None:
    message = agent_domain.TextMessage(
        **_valid_message_kwargs(
            source=agent_domain.StimulusSource.WORLD,
            user_id=None,
            ephemeral=True,
        )
    )

    assert message.source is agent_domain.StimulusSource.WORLD
    assert message.user_id is None
    assert message.ephemeral is True


def test_text_message_constructor_is_keyword_only() -> None:
    parameters = signature(agent_domain.TextMessage).parameters

    for field_name in _valid_message_kwargs():
        assert parameters[field_name].kind is Parameter.KEYWORD_ONLY


@pytest.mark.parametrize(
    "omitted_field",
    [
        "stimulus_id",
        "schema_version",
        "occurred_at",
        "source",
        "target_character_ids",
        "user_id",
        "ephemeral",
        "text",
        "client_msg_id",
    ],
)
def test_text_message_rejects_an_omitted_required_field(omitted_field: str) -> None:
    _assert_invalid_stimulus(
        "CONTRACT_INVALID_STIMULUS",
        omitted_field=omitted_field,
    )


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("stimulus_id", " \t"),
        ("stimulus_id", 7),
        ("occurred_at", datetime(2026, 9, 5, 8, 30)),
        ("occurred_at", "2026-09-05T08:30:00Z"),
        ("source", "user"),
        ("target_character_ids", ()),
        ("target_character_ids", ["luotianyi"]),
        ("target_character_ids", ("luotianyi", " \t")),
        ("target_character_ids", ("luotianyi", 7)),
        ("user_id", " \t"),
        ("user_id", 7),
        ("ephemeral", 0),
        ("text", " \t\n"),
        ("text", 7),
        ("client_msg_id", " \t"),
        ("client_msg_id", 7),
    ],
)
def test_text_message_rejects_an_invalid_field(
    field_name: str,
    invalid_value: object,
) -> None:
    _assert_invalid_stimulus(
        "CONTRACT_INVALID_STIMULUS",
        **{field_name: invalid_value},
    )


@pytest.mark.parametrize("invalid_version", [True, 1.0, "1"])
def test_text_message_rejects_a_non_integer_schema_version(
    invalid_version: object,
) -> None:
    _assert_invalid_stimulus(
        "CONTRACT_INVALID_STIMULUS",
        schema_version=invalid_version,
    )


@pytest.mark.parametrize("unsupported_version", [-1, 0, 2])
def test_text_message_rejects_an_unsupported_integer_schema_version(
    unsupported_version: int,
) -> None:
    _assert_invalid_stimulus(
        "CONTRACT_UNSUPPORTED_SCHEMA",
        schema_version=unsupported_version,
    )


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("kind", "text_message"),
        ("payload", {"text": "你好"}),
        ("persist_policy", "conversation_only"),
    ],
)
def test_text_message_does_not_accept_caller_controlled_protocol_fields(
    field_name: str,
    field_value: object,
) -> None:
    values = _valid_message_kwargs(**{field_name: field_value})

    with pytest.raises((TypeError, agent_domain.InvalidStimulusError)):
        agent_domain.TextMessage(**values)


def test_legacy_stimulus_keeps_its_own_persistence_protocol() -> None:
    from src.domain.stimulus import (
        PersistPolicy,
        SourceChannel,
        Stimulus as LegacyStimulus,
        StimulusModality,
    )

    legacy_stimulus = LegacyStimulus(
        source_channel=SourceChannel.WEBSOCKET,
        modality=StimulusModality.TEXT,
        persist_policy=PersistPolicy.CONVERSATION_AND_MEMORY_CANDIDATE,
    )

    assert legacy_stimulus.should_persist_conversation() is True
    assert legacy_stimulus.can_be_memory_candidate() is True
