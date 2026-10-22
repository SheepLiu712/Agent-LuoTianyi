import pytest

from src.agent.skills.adapters.memory.profile_updater import UserProfileUpdater


class Model:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    async def generate_response(self, **_kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


@pytest.mark.asyncio
async def test_profile_model_failure_warns_once_and_preserves_profile(caplog, capture_project_log):
    capture_project_log("UserProfileUpdater")
    model = Model(error=RuntimeError("model unavailable"))
    updater = UserProfileUpdater({}, model)

    with caplog.at_level("WARNING"):
        result = await updater.update_profile({"summary": "", "recent_conversation": []}, "既有画像")

    assert result == ""
    assert model.calls == 1
    warnings = [record for record in caplog.records if "User profile update LLM call failed" in record.message]
    assert len(warnings) == 1
    assert warnings[0].levelname == "WARNING"


@pytest.mark.asyncio
async def test_profile_no_update_is_not_reported_as_model_failure(caplog, capture_project_log):
    capture_project_log("UserProfileUpdater")
    model = Model(result="no_update")
    updater = UserProfileUpdater({}, model)

    with caplog.at_level("WARNING"):
        result = await updater.update_profile({"summary": "", "recent_conversation": []}, "既有画像")

    assert result == ""
    assert model.calls == 1
    assert not [record for record in caplog.records if "User profile update LLM call failed" in record.message]
