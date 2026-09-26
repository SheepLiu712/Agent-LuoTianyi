from src.cli.actions import ActionExecutor, ExitCode
from src.cli import auth_store
from src.session import SessionState


class AccountSession:
    def __init__(self, *, registration=(True, "ok")):
        self.state = SessionState.NEW
        self.registration = registration
        self.calls = []

    def register(self, username, password, invite_code):
        self.calls.append((username, password, invite_code))
        return self.registration

    def close(self):
        pass


def test_registration_uses_client_api_and_reports_result_without_secrets():
    session = AccountSession()
    executor = ActionExecutor(session_factory=lambda **_: session)
    record, code = executor.execute(
        {
            "action": "account.register",
            "params": {
                "base_url": "https://example.test",
                "username": "new-user",
                "password": "secret-value",
                "password_confirm": "secret-value",
                "invite_code": "invite-value",
            },
        }
    )
    assert code == ExitCode.SUCCESS
    assert record["status"] == "passed"
    assert session.calls == [("new-user", "secret-value", "invite-value")]
    assert "secret-value" not in str(record)
    assert "invite-value" not in str(record)


def test_registration_rejects_mismatched_password_before_network_request():
    session = AccountSession()
    executor = ActionExecutor(session_factory=lambda **_: session)
    record, code = executor.execute(
        {
            "action": "account.register",
            "params": {
                "base_url": "https://example.test",
                "username": "new-user",
                "password": "first",
                "password_confirm": "second",
                "invite_code": "invite-value",
            },
        }
    )
    assert code == ExitCode.INPUT_ERROR
    assert record["error"]["code"] == "PASSWORD_MISMATCH"
    assert session.calls == []


def test_server_rejects_invalid_invite_code():
    session = AccountSession(registration=(False, "invalid invite"))
    executor = ActionExecutor(session_factory=lambda **_: session)
    record, code = executor.execute(
        {
            "action": "account.register",
            "params": {
                "base_url": "https://example.test",
                "username": "new-user",
                "password": "secret-value",
                "password_confirm": "secret-value",
                "invite_code": "bad-code",
            },
        }
    )
    assert code == ExitCode.ASSERTION_FAILED
    assert record["error"]["code"] == "REGISTRATION_FAILED"


class LoginSession(AccountSession):
    def __init__(self):
        super().__init__()
        self.login_token = "rotating-login-token"

    def connect(self, username, password, *, timeout, request_token=False):
        self.calls.append(("connect", username, password, request_token))
        self.state = SessionState.READY

    def connect_with_token(self, username, token, *, timeout):
        self.calls.append(("auto_connect", username, token))
        self.state = SessionState.READY


def test_explicit_remember_login_uses_isolated_encrypted_store(tmp_path, monkeypatch):
    monkeypatch.setattr(auth_store, "encrypt_secret", lambda _value: "opaque-ciphertext")
    monkeypatch.setattr(auth_store, "decrypt_secret", lambda _value: "rotating-login-token")
    sessions = []

    def factory(**_):
        session = LoginSession()
        sessions.append(session)
        return session

    credential_file = tmp_path / "cli-login.json"
    first = ActionExecutor(session_factory=factory)
    record, code = first.execute(
        {
            "action": "session.connect",
            "params": {
                "base_url": "https://example.test",
                "username": "new-user",
                "password": "secret",
                "remember_login": True,
                "credential_file": str(credential_file),
            },
        }
    )
    assert code == ExitCode.SUCCESS
    assert sessions[0].calls[0] == ("connect", "new-user", "secret", True)
    assert "rotating-login-token" not in credential_file.read_text()
    assert record["data"]["state"] == "ready"

    later = ActionExecutor(session_factory=factory)
    record, code = later.execute(
        {
            "action": "session.auto_connect",
            "params": {"credential_file": str(credential_file)},
        }
    )
    assert code == ExitCode.SUCCESS
    assert record["data"]["state"] == "ready"
    assert sessions[1].calls[0] == ("auto_connect", "new-user", "rotating-login-token")
