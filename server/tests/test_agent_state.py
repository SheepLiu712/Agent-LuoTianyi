import os
import sys

current_dir = os.getcwd()
if current_dir not in sys.path:
    sys.path.append(current_dir)

from src.domain import AgentState
from src.subconscious import SubconsciousState


def test_agent_state_clamps_unit_metrics():
    state = AgentState(owner_character_id="luotianyi")

    updated = state.with_updates(
        mood=1.5,
        arousal=-0.5,
        vitality=0.25,
        connection_need=2.0,
        attention_bias=("music",),
    )

    assert updated.owner_character_id == "luotianyi"
    assert updated.mood == 1.0
    assert updated.arousal == 0.0
    assert updated.vitality == 0.25
    assert updated.connection_need == 1.0
    assert updated.attention_bias == ("music",)


def test_subconscious_state_is_independent_per_character():
    luotianyi_state = SubconsciousState(owner_character_id="luotianyi")
    yanhe_state = SubconsciousState(owner_character_id="yanhe")

    luotianyi_state.update(mood=0.9, attention_bias=("user_message",))

    assert luotianyi_state.get_snapshot().owner_character_id == "luotianyi"
    assert yanhe_state.get_snapshot().owner_character_id == "yanhe"
    assert luotianyi_state.get_snapshot().mood == 0.9
    assert yanhe_state.get_snapshot().mood != 0.9
    assert luotianyi_state.get_snapshot().attention_bias == ("user_message",)
    assert yanhe_state.get_snapshot().attention_bias == ()


def test_subconscious_state_rejects_wrong_owner_snapshot():
    service = SubconsciousState(owner_character_id="luotianyi")
    wrong = AgentState(owner_character_id="yanhe")

    try:
        service.replace_snapshot(wrong)
    except ValueError as exc:
        assert "owner mismatch" in str(exc)
    else:
        raise AssertionError("expected owner mismatch")
