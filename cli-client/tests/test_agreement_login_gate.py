"""CLI 网络登录路径对协议豁免和升级门禁的本地集成证据。"""

# ruff: noqa: E402

import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

CLI_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = CLI_ROOT.parent / "server"
for root in (CLI_ROOT, SERVER_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from cli_client.network.network_client import NetworkClient
from cli_client.safety import encrypt_pwd
from src.application.user.agreement_service import AgreementService
from src.infrastructure.media import create_media_resolver
from src.infrastructure.persistence.database.database_service import DatabaseManager
from src.infrastructure.persistence.database.services import credential_service
from src.infrastructure.persistence.database.sql_database import AgreementVersion, User
from src.web.http import routes
from src.web.http import user_interface as user_interface_module
from src.web.http.user_interface import UserInterface

V1 = "terms-cli-v1"


class InProcessHttpSession:
    """将 requests 风格 CLI HTTP 调用接到同进程真实 FastAPI 路由。"""

    def __init__(self, client: TestClient) -> None:
        self._client = client

    def get(self, url, **kwargs):
        return self._client.get(urlsplit(url).path, params=kwargs.get("params"))

    def post(self, url, **kwargs):
        return self._client.post(urlsplit(url).path, json=kwargs.get("json"))


@pytest.fixture
def cli_agreement_server(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "cli-agreement-test-secret")
    monkeypatch.setattr(
        credential_service, "_hash_password", lambda value: f"hash:{value}"
    )
    monkeypatch.setattr(
        credential_service,
        "_is_bcrypt_hash",
        lambda value: bool(value and value.startswith("hash:")),
    )
    monkeypatch.setattr(
        credential_service,
        "_verify_password",
        lambda value, stored: stored == f"hash:{value}",
    )
    monkeypatch.setattr(
        user_interface_module, "enforce_rate_limit", lambda *args, **kwargs: None
    )
    manager = DatabaseManager(
        {"sql_db_folder": str(tmp_path / "db"), "sql_db_file": "cli-agreement.db"}
    )
    session = manager.open_sql_session()
    try:
        session.add(
            AgreementVersion(
                version=V1,
                title="用户协议",
                format="agreement.richtext.v1",
                content_json="[]",
                content_sha256="0" * 64,
                created_at="2026-10-10T14:30:25+08:00",
            )
        )
        session.add(
            User(uuid="cli-exempt", username="exempt", password="hash:password")
        )
        session.add(
            User(uuid="cli-ordinary", username="ordinary", password="hash:password")
        )
        session.commit()
    finally:
        session.close()

    interface = UserInterface(manager, create_media_resolver())
    interface.generate_rsa_keys()
    runtime = SimpleNamespace(
        database_manager=manager,
        agreement_service=AgreementService(V1, {}, {"cli-exempt"}),
        agent_runtime=SimpleNamespace(default_character_id="luotianyi"),
        stage_manager=SimpleNamespace(record_login=lambda *args, **kwargs: None),
        user_interface=interface,
    )
    manager.conversation_service.prefill_buffer = lambda _user_uuid: None
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client


@pytest.fixture(autouse=True)
def clear_cli_public_key_cache():
    encrypt_pwd.public_key = None
    encrypt_pwd.public_key_cache_key = None
    yield
    encrypt_pwd.public_key = None
    encrypt_pwd.public_key_cache_key = None


def _cli_client(monkeypatch, server_client):
    session = InProcessHttpSession(server_client)
    monkeypatch.setattr(
        encrypt_pwd.HttpClientFactory, "get_session", lambda **_kwargs: session
    )
    client = NetworkClient("http://cli-agreement.test")
    client.auth_api.session = session
    monkeypatch.setattr(client.ws_transport, "start", lambda: None)
    return client


def test_cli_exempt_user_uses_real_auth_api_and_network_session_path(
    cli_agreement_server, monkeypatch
):
    client = _cli_client(monkeypatch, cli_agreement_server)

    success, message = client.login("exempt", "password")

    assert (success, message) == (True, "Login Successful")
    assert client.user_id == "exempt"
    assert client.login_token
    assert client.message_token


def test_cli_unsigned_ordinary_user_receives_upgrade_text_from_real_auth_path(
    cli_agreement_server, monkeypatch
):
    client = _cli_client(monkeypatch, cli_agreement_server)

    success, message = client.login("ordinary", "password")

    assert success is False
    assert message == "请升级到支持用户协议签署的版本，阅读并同意用户协议后再登录。"
