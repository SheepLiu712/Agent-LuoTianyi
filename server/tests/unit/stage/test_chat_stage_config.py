"""Chat ending permits a 90-second maintenance budget, with explicit overrides."""

import pytest

from src.stage._config import _StageConfig


def test_chat_maintenance_defaults_to_ninety_seconds():
    assert _StageConfig().termination_timeout == 90.0
    assert _StageConfig.from_dict({}).termination_timeout == 90.0


def test_chat_maintenance_explicit_timeout_is_preserved():
    assert _StageConfig.from_dict({"termination_timeout": 5}).termination_timeout == 5


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan"), True])
def test_chat_maintenance_rejects_invalid_timeout(value):
    with pytest.raises(ValueError, match="termination_timeout"):
        _StageConfig.from_dict({"termination_timeout": value})
