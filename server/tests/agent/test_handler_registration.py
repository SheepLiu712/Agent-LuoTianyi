"""路由自身只验证登记与精确解析，不通过私有映射断言实现。"""
import pytest

import src.domain.agent as d
from routing_support import router_type


@pytest.mark.parametrize("side,kinds", [
    ("stimulus", (d.StimulusKind.TEXT_MESSAGE, d.StimulusKind.VOICE_MESSAGE)),
    ("action", (d.ActionKind.SAY, d.ActionKind.SING)),
])
def test_registration_preserves_identity_and_snapshots_source(side, kinds):
    cls = router_type(side)
    first, second = object(), object()
    registrations = [(kinds[0], first), (kinds[1], first)]
    router = cls(iter(registrations))
    registrations[0] = (kinds[0], second)
    assert router.resolve(kinds[0]) is first
    assert router.resolve(kinds[1]) is first
    assert cls([(kinds[0], second)]).resolve(kinds[0]) is second


@pytest.mark.parametrize("side,kind", [("stimulus", d.StimulusKind.TEXT_MESSAGE), ("action", d.ActionKind.SAY)])
@pytest.mark.parametrize("same", [True, False])
def test_duplicate_kind_is_rejected_even_for_same_object(side, kind, same):
    cls = router_type(side)
    handler = object()
    with pytest.raises(ValueError):
        cls([(kind, handler), (kind, handler if same else object())])


@pytest.mark.parametrize("side,kind", [("stimulus", d.StimulusKind.TEXT_MESSAGE), ("action", d.ActionKind.SAY)])
@pytest.mark.parametrize("invalid", ["string_key", "other_enum", "none_handler", "wrong_pair", "not_iterable"])
def test_invalid_registration_fails_without_fallback(side, kind, invalid):
    cls = router_type(side)
    bad = {
        "string_key": [(kind.value, object())],
        "other_enum": [(d.ActionKind.SAY if side == "stimulus" else d.StimulusKind.TEXT_MESSAGE, object())],
        "none_handler": [(kind, None)], "wrong_pair": [(kind,)], "not_iterable": None,
    }[invalid]
    with pytest.raises(TypeError):
        cls(bad)


@pytest.mark.parametrize("side,kind", [("stimulus", d.StimulusKind.TEXT_MESSAGE), ("action", d.ActionKind.SAY)])
def test_empty_registry_and_wrong_lookup_key_are_distinct(side, kind):
    router = router_type(side)([])
    with pytest.raises(KeyError) as error:
        router.resolve(kind)
    assert error.value.args == (kind,)
    with pytest.raises(TypeError):
        router.resolve(kind.value)


def test_stage_thinking_action_cannot_be_registered():
    cls = router_type("action")
    with pytest.raises(ValueError):
        cls([(d.ActionKind.START_THINKING, object())])
    with pytest.raises(KeyError):
        cls([]).resolve(d.ActionKind.START_THINKING)
