from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests
from sqlalchemy import create_engine, text

_SERVER_MODULE = "support.call_network_success_server"
_SERVER_BOOTSTRAP = """
import os
import runpy
import sys
import time

started = time.monotonic()
os.environ["CALL_TEST_START_MONOTONIC"] = repr(started)
print(
    "CALL_TEST_PHASE python-entered"
    f" elapsed=0.000 pid={os.getpid()}"
    f" executable={sys.executable} prefix={sys.prefix} base_prefix={sys.base_prefix}",
    flush=True,
)
sys.argv = ["support.call_network_success_server", sys.argv[1]]
runpy.run_module("support.call_network_success_server", run_name="__main__")
"""


def _server_command(root: Path) -> list[str]:
    return [sys.executable, "-u", "-c", _SERVER_BOOTSTRAP, str(root)]


def _expected_server_source() -> str:
    source = Path(__file__).resolve().parents[2] / "support" / f"{_SERVER_MODULE.rsplit('.', 1)[-1]}.py"
    return os.path.normcase(os.path.normpath(str(source.resolve())))


def _start_server(root: Path):
    repo = Path(__file__).resolve().parents[4]
    log_path = root / f"server-{time.time_ns()}.log"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(repo / "server"), str(repo / "server/tests"), env.get("PYTHONPATH", "")])
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(key, None)
    log = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        _server_command(root),
        cwd=root,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    session = requests.Session()
    session.trust_env = False
    address = root / "address.json"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log.close()
            raise AssertionError(log_path.read_text(encoding="utf-8"))
        if address.exists():
            url = json.loads(address.read_text(encoding="utf-8"))["url"]
            try:
                if session.get(url + "/test/evidence", timeout=0.5).ok:
                    return process, session, url, log, log_path
            except requests.RequestException:
                pass
        time.sleep(0.05)
    process.kill()
    process.wait(timeout=5)
    log.close()
    raise AssertionError("restart server readiness timed out\n" + log_path.read_text(encoding="utf-8"))


def _stop_server(process, session, url, log, log_path):
    try:
        session.post(url + "/test/stop", timeout=2)
    finally:
        if process.poll() is None:
            process.wait(timeout=15)
        session.close()
        log.close()
    assert process.returncode == 0, log_path.read_text(encoding="utf-8")


def _start_server_expect_failure(root: Path) -> str:
    repo = Path(__file__).resolve().parents[4]
    log_path = root / f"server-failed-{time.time_ns()}.log"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(repo / "server"), str(repo / "server/tests"), env.get("PYTHONPATH", "")])
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(key, None)
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            _server_command(root),
            cwd=root,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        process.wait(timeout=30)
    output = log_path.read_text(encoding="utf-8")
    assert process.returncode != 0
    assert "production runtime did not become ready" in output
    return output


def _encrypted_password(session, url: str, password: str) -> str:
    from base64 import b64encode

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    public_key = session.get(url + "/auth/public_key", timeout=5).json()["public_key"]
    key = serialization.load_pem_public_key(public_key.encode("utf-8"))
    return b64encode(
        key.encrypt(
            password.encode("utf-8"),
            padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
        )
    ).decode("ascii")


def _login(session, url: str) -> str:
    response = session.post(
        url + "/auth/login",
        json={"username": "alice", "password": _encrypted_password(session, url, "offline-password")},
        timeout=10,
    )
    assert response.ok, response.text
    return response.json()["message_token"]


def test_production_process_restart_recovers_recent_calls_once_and_preserves_credentials(tmp_path):
    root = tmp_path / "restart-runtime"
    root.mkdir()
    first = _start_server(root)
    process, http, url, log, log_path = first
    try:
        registered = http.post(
            url + "/auth/register",
            json={
                "username": "alice",
                "password": _encrypted_password(http, url, "offline-password"),
                "invite_code": "invite",
            },
            timeout=10,
        )
        assert registered.ok, registered.text
        assert _login(http, url)
        seeded = http.post(url + "/test/seed_stale_calls", timeout=10).json()
    finally:
        _stop_server(process, http, url, log, log_path)

    expected = None
    for restart in range(2):
        process, http, url, log, log_path = _start_server(root)
        try:
            token = _login(http, url)
            capability = http.get(
                url + "/call/capability?character_id=luotianyi",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )
            assert capability.status_code == 200
            evidence = http.get(url + "/test/recovery_counts", timeout=5).json()
            by_id = {item["call_id"]: item for item in evidence["calls"]}
            assert by_id[seeded["preparing_call_id"]]["state"] == "failed"
            active = by_id[seeded["active_call_id"]]
            assert active["state"] == "ended"
            assert active["summary_status"] == "succeeded"
            assert active["maintenance_status"] == "failed"
            assert active["conversation_id"] is not None
            assert evidence["call_conversations"] == 1
            assert evidence["maintenance_batches"] == 0
            current = (active["conversation_id"], evidence["call_conversations"], evidence["maintenance_batches"])
            if expected is None:
                expected = current
            else:
                assert current == expected
        finally:
            _stop_server(process, http, url, log, log_path)


def test_production_startup_fails_closed_on_recovery_conflict_without_late_writes(tmp_path):
    root = tmp_path / "failed-restart-runtime"
    root.mkdir()
    process, http, url, log, log_path = _start_server(root)
    try:
        registered = http.post(
            url + "/auth/register",
            json={
                "username": "alice",
                "password": _encrypted_password(http, url, "offline-password"),
                "invite_code": "invite",
            },
            timeout=10,
        )
        assert registered.ok, registered.text
        seeded = http.post(url + "/test/seed_recovery_conflict", timeout=10).json()
    finally:
        _stop_server(process, http, url, log, log_path)

    _start_server_expect_failure(root)
    database_path = root / "db" / "calls.sqlite"
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        first = connection.execute(
            text("SELECT state, summary_status, maintenance_status FROM call_sessions WHERE call_id=:call_id"),
            {"call_id": seeded["call_id"]},
        ).one()
        conversation_count = connection.execute(
            text("SELECT COUNT(*) FROM conversations WHERE type='call'")
        ).scalar_one()
    time.sleep(0.2)
    with engine.connect() as connection:
        second = connection.execute(
            text("SELECT state, summary_status, maintenance_status FROM call_sessions WHERE call_id=:call_id"),
            {"call_id": seeded["call_id"]},
        ).one()
        assert (
            connection.execute(text("SELECT COUNT(*) FROM conversations WHERE type='call'")).scalar_one()
            == conversation_count
        )
    engine.dispose()
    assert first == second
    assert first == ("ended", "pending", "pending")
    assert conversation_count == 1


def test_process_restart_repairs_partial_summary_and_maintenance_exactly_once(tmp_path):
    root = tmp_path / "partial-settlement-restart"
    root.mkdir()
    process, http, url, log, log_path = _start_server(root)
    try:
        registered = http.post(
            url + "/auth/register",
            json={
                "username": "alice",
                "password": _encrypted_password(http, url, "offline-password"),
                "invite_code": "invite",
            },
            timeout=10,
        )
        assert registered.ok, registered.text
        seeded = http.post(url + "/test/seed_partial_settlement", timeout=10).json()
    finally:
        _stop_server(process, http, url, log, log_path)

    expected = None
    for _restart in range(2):
        process, http, url, log, log_path = _start_server(root)
        try:
            evidence = http.get(url + "/test/recovery_counts", timeout=5).json()
            by_id = {item["call_id"]: item for item in evidence["calls"]}
            summary = by_id[seeded["summary_call_id"]]
            maintenance = by_id[seeded["maintenance_call_id"]]
            assert summary["summary_status"] == "succeeded"
            assert summary["conversation_id"] == seeded["summary_conversation_id"]
            assert maintenance["maintenance_status"] == "succeeded"
            assert maintenance["maintenance_turn_seq"] == 1
            assert evidence["call_conversations"] == 1
            assert evidence["maintenance_batches"] == 1
            current = (
                summary["conversation_id"],
                maintenance["maintenance_turn_seq"],
                evidence["call_conversations"],
                evidence["maintenance_batches"],
                evidence["profile"],
            )
            if expected is None:
                expected = current
            else:
                assert current == expected
        finally:
            _stop_server(process, http, url, log, log_path)


def test_issue_324_production_deadline_survives_two_real_runtime_restarts(tmp_path):
    root = tmp_path / "issue-324-deadline-restart"
    root.mkdir()
    process, http, url, log, log_path = _start_server(root)
    try:
        registered = http.post(
            url + "/auth/register",
            json={
                "username": "alice",
                "password": _encrypted_password(http, url, "offline-password"),
                "invite_code": "invite",
            },
            timeout=10,
        )
        assert registered.ok, registered.text
        deadline = http.post(url + "/test/issue_324/deadline", timeout=30).json()
        assert deadline["summary_status"] == "succeeded"
        assert deadline["maintenance_status"] == "failed"
        assert deadline["call_conversations"] == 1
        assert deadline["maintenance_started"]
        assert deadline["maintenance_stopped"]
        assert os.path.normcase(os.path.normpath(deadline["source"])) == _expected_server_source()
    finally:
        _stop_server(process, http, url, log, log_path)

    expected = None
    for _restart in range(2):
        process, http, url, log, log_path = _start_server(root)
        try:
            evidence = http.get(url + "/test/recovery_counts", timeout=5).json()
            by_id = {item["call_id"]: item for item in evidence["calls"]}
            record = by_id[deadline["call_id"]]
            assert record["summary_status"] == "succeeded"
            assert record["maintenance_status"] == "failed"
            assert record["conversation_id"] == deadline["conversation_id"]
            assert evidence["call_conversations"] == 1
            current = (record["conversation_id"], evidence["call_conversations"], evidence["maintenance_batches"])
            if expected is None:
                expected = current
            else:
                assert current == expected
        finally:
            _stop_server(process, http, url, log, log_path)
