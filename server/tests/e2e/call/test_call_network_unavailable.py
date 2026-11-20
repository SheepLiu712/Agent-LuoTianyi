"""Real loopback E2E coverage for safe call capability rejection.

This is intentionally a bounded support harness, not a claim that it covers
the separate full-call lifecycle acceptance suite.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests
import websocket


@pytest.fixture(params=["unknown", "multiworker"])
def gated_call_server(tmp_path, request):
    repo = Path(__file__).resolve().parents[4]
    root = tmp_path / request.param
    root.mkdir()
    log_path = root / "server.log"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(repo / "server"), str(repo / "server/tests"), env.get("PYTHONPATH", "")])
    env["PYTHONIOENCODING"] = "utf-8"
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(key, None)
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "support.call_network_unavailable_server", str(root), request.param],
            cwd=root,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        session = requests.Session()
        session.trust_env = False
        url = None
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                assert process.poll() is None, log_path.read_text(encoding="utf-8")
                address = root / "address.json"
                if address.exists():
                    url = json.loads(address.read_text(encoding="utf-8"))["url"]
                    try:
                        if session.get(url + "/test/evidence", timeout=0.5).ok:
                            break
                    except requests.RequestException:
                        pass
                time.sleep(0.05)
            else:
                pytest.fail("call gate server readiness timed out\n" + log_path.read_text(encoding="utf-8"))
            yield url, session, root
        finally:
            if process.poll() is None and url is not None:
                try:
                    session.post(url + "/test/stop", timeout=2)
                except requests.RequestException:
                    pass
            if process.poll() is None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            session.close()
            assert process.returncode == 0, log_path.read_text(encoding="utf-8")


def _authenticate(ws, token):
    assert json.loads(ws.recv())["type"] == "system_ready"
    ws.send(
        json.dumps(
            {
                "type": "user_auth",
                "client_msg_id": "auth-1",
                "payload": {"username": "alice", "token": token},
            }
        )
    )
    assert json.loads(ws.recv())["type"] == "auth_ok"


def test_real_network_call_gate_keeps_chat_auth_available(gated_call_server):
    url, http, root = gated_call_server
    evidence = http.get(url + "/test/evidence", timeout=5).json()
    assert evidence["call_transport_available"] is False
    assert evidence["call_capability"]["enabled"] is True
    assert evidence["call_capability"]["trusted_host"] is False
    ws_url = "ws" + url[4:]

    chat = websocket.create_connection(ws_url + "/chat_ws", timeout=5, http_proxy_host=None)
    try:
        _authenticate(chat, evidence["message_token"])
    finally:
        chat.close()

    call = websocket.create_connection(ws_url + "/call_ws", timeout=5, http_proxy_host=None)
    try:
        first = call.recv()
        assert first in ("", b"")
        assert call.connected is False
    finally:
        call.close()

    persisted = (root / "db" / "calls.sqlite").read_bytes()
    logs = (root / "server.log").read_text(encoding="utf-8")
    for forbidden in ("你还记得我喜欢什么吗", "用户喜欢音乐", "AQIDBA=="):
        assert forbidden.encode("utf-8") not in persisted
        assert forbidden not in logs
