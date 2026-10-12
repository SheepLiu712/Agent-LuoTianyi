from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.server_runtime import CallCapabilityStatus
from src.web.http import routes
from src.web.http.user_interface import UserInterface


class _Resolver:
    def ensure_dependencies(self):
        pass


def _runtime(status, *, supported=True, token="good-token"):
    credentials = SimpleNamespace(authenticate_message_token=lambda value: "owner" if value == token else None)
    database = SimpleNamespace(credential_service=credentials)
    runtime = SimpleNamespace(database_manager=database, call_capability_status=status)
    runtime.supports_call_character = lambda character_id: supported and character_id == "luotianyi"
    runtime.user_interface = UserInterface(database, _Resolver())
    return runtime


def _client(runtime):
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.get_runtime] = lambda: runtime
    return TestClient(app)


def test_call_capability_requires_bearer_message_token_and_never_accepts_username():
    status = CallCapabilityStatus(*(True for _ in range(8)), ("luotianyi",))
    with _client(_runtime(status)) as client:
        assert client.get("/call/capability?character_id=luotianyi").status_code == 401
        assert (
            client.get(
                "/call/capability?character_id=luotianyi&username=owner",
                headers={"Authorization": "Bearer wrong-token"},
            ).status_code
            == 401
        )
        response = client.get(
            "/call/capability?character_id=luotianyi&username=someone-else",
            headers={"Authorization": "Bearer good-token"},
        )
    assert response.status_code == 200
    assert response.json() == {"available": True, "character_id": "luotianyi", "reason": "available"}


def test_call_capability_projects_each_readiness_failure_without_runtime_details():
    reasons = (
        "disabled",
        "untrusted_host",
        "provider_unavailable",
        "call_tts_unavailable",
        "summary_unavailable",
        "settlement_unavailable",
        "stage_binding_unavailable",
        "recovery_unavailable",
    )
    for index, reason in enumerate(reasons):
        values = [True] * 8
        values[index] = False
        status = CallCapabilityStatus(*values, ("luotianyi",))
        with _client(_runtime(status)) as client:
            response = client.get(
                "/call/capability?character_id=luotianyi", headers={"Authorization": "Bearer good-token"}
            )
        assert response.json() == {"available": False, "character_id": "luotianyi", "reason": reason}
        assert "secret" not in response.text.lower()


def test_call_capability_rejects_unknown_characters_and_invalid_query_shape():
    status = CallCapabilityStatus(*(True for _ in range(8)), ("luotianyi",))
    with _client(_runtime(status, supported=False)) as client:
        response = client.get("/call/capability?character_id=other", headers={"Authorization": "Bearer good-token"})
        assert response.json() == {"available": False, "character_id": "other", "reason": "character_unavailable"}
        assert client.get("/call/capability", headers={"Authorization": "Bearer good-token"}).status_code == 422
        assert (
            client.get("/call/capability?character_id=", headers={"Authorization": "Bearer good-token"}).status_code
            == 422
        )


def test_call_capability_returns_runtime_not_ready_when_readiness_status_is_absent():
    runtime = _runtime(None)
    with _client(runtime) as client:
        response = client.get("/call/capability?character_id=luotianyi", headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    assert response.json() == {"available": False, "character_id": "luotianyi", "reason": "runtime_not_ready"}
