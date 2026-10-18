"""Real loopback acceptance coverage for the successful call.v1 lifecycle."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests
import websocket
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from src.adapter.websocket.call_v1._audio_codec import CALL_ROUTE, VERSION, BinaryAudioFrameCodec, WireAudioFrame


@pytest.fixture
def successful_call_server(tmp_path):
    repo = Path(__file__).resolve().parents[4]
    root = tmp_path / "successful-call"
    root.mkdir()
    log_path = root / "server.log"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(repo / "server"), str(repo / "server/tests"), env.get("PYTHONPATH", "")])
    env["PYTHONIOENCODING"] = "utf-8"
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        env.pop(key, None)
    stdout_path = root / "stdout.log"
    stderr_path = root / "stderr.log"
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(
            [sys.executable, "-m", "support.call_network_success_server", str(root)],
            cwd=root,
            env=env,
            stdout=stdout,
            stderr=stderr,
        )
        session = requests.Session()
        session.trust_env = False
        url = None
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                assert process.poll() is None, _process_output(stdout_path, stderr_path)
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
                pytest.fail("successful call server readiness timed out\n" + _process_output(stdout_path, stderr_path))
            yield url, session, root
        finally:
            if process.poll() is None and url is not None:
                _release_test_write(session, url)
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
            stdout.flush()
            stderr.flush()
            log_path.write_text(_process_output(stdout_path, stderr_path), encoding="utf-8")
            assert process.returncode == 0, log_path.read_text(encoding="utf-8")


def _release_test_write(session, url):
    try:
        session.post(url + "/test/settlement_write/release", timeout=2)
    except requests.RequestException:
        pass


def _process_output(stdout_path: Path, stderr_path: Path) -> str:
    return stdout_path.read_text(encoding="utf-8") + stderr_path.read_text(encoding="utf-8")


def _encrypted_password(http: requests.Session, url: str, password: str) -> str:
    public_key = serialization.load_pem_public_key(
        http.get(url + "/auth/public_key", timeout=5).json()["public_key"].encode()
    )
    encrypted = public_key.encrypt(
        password.encode(),
        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )
    return base64.b64encode(encrypted).decode()


def _authenticate(ws, token: str) -> None:
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


def _receive_chat_ready(ws, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        event = json.loads(ws.recv())
        if event.get("type") == "chat.ready":
            return event
    raise AssertionError("did not receive chat.ready")


def _control(ws, message: dict) -> None:
    ws.send(json.dumps(message, separators=(",", ":")))


def _receive_until(ws, expected_type: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        raw = ws.recv()
        if isinstance(raw, bytes):
            continue
        event = json.loads(raw)
        if event.get("type") == expected_type:
            return event
    raise AssertionError(f"did not receive {expected_type}")


def _receive_chat_switch_ready(ws, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        event = json.loads(ws.recv())
        if event.get("type") == "call.switch_ready":
            return event
        payload = event.get("payload")
        if isinstance(payload, dict) and payload.get("type") == "call.switch_ready":
            return payload
    raise AssertionError("did not receive call.switch_ready")


def _complete(ws, call_id: str, sequence: int, stream: dict) -> None:
    _control(
        ws,
        {
            "protocol": "call.v1",
            "type": "playback.completed",
            "seq": sequence,
            "call_id": call_id,
            "response_id": stream["response_id"],
            "stream_id": stream["stream_id"],
        },
    )


def _start_call(ws, request_id: str) -> str:
    _control(
        ws,
        {
            "protocol": "call.v1",
            "type": "call.start",
            "seq": 1,
            "client_request_id": request_id,
            "character_id": "luotianyi",
            "audio": {"encoding": "pcm_s16le", "sample_rate": 16000, "channels": 1},
        },
    )
    preparing = _receive_until(ws, "call.state")
    assert preparing["state"] == "preparing"
    assert _receive_until(ws, "ack")["ack_seq"] == 1
    assert _receive_until(ws, "call.active")["call_id"] == preparing["call_id"]
    return preparing["call_id"]


def _hangup(ws, call_id: str, sequence: int = 2) -> None:
    _control(
        ws,
        {
            "protocol": "call.v1",
            "type": "call.hangup",
            "seq": sequence,
            "call_id": call_id,
            "reason": "user_hangup",
        },
    )
    assert _receive_until(ws, "call.ended", timeout=10)["end_reason"] == "user_hangup"


def test_production_entry_finalization_blocks_then_restores_chat_and_call(
    successful_call_server,
):
    url, http, _root = successful_call_server
    password = "offline-password"
    assert http.post(
        url + "/auth/register",
        json={
            "username": "alice",
            "password": _encrypted_password(http, url, password),
            "invite_code": "invite",
        },
        timeout=10,
    ).ok
    login = http.post(
        url + "/auth/login",
        json={
            "username": "alice",
            "password": _encrypted_password(http, url, password),
        },
        timeout=10,
    )
    token = login.json()["message_token"]
    ws_url = "ws" + url[4:]

    chat = websocket.create_connection(ws_url + "/chat_ws", timeout=5, http_proxy_host=None)
    _authenticate(chat, token)
    _receive_chat_ready(chat)
    chat.send(
        json.dumps(
            {
                "protocol": "call.v1",
                "type": "call.switch_prepare",
                "client_request_id": "finalizing-call-1",
                "character_id": "luotianyi",
            }
        )
    )
    assert _receive_chat_switch_ready(chat)["type"] == "call.switch_ready"
    chat.close()

    call = websocket.create_connection(ws_url + "/call_ws", timeout=5, http_proxy_host=None)
    _authenticate(call, token)
    first_call_id = _start_call(call, "finalizing-call-1")
    assert http.post(url + "/test/settlement_write/block_next", timeout=5).ok
    _hangup(call, first_call_id)
    call.close()

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if http.get(url + "/test/settlement_write/status", timeout=5).json()["entered"]:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("settlement write did not enter the controlled barrier")

    reset = http.post(
        url + "/user/data/reset",
        json={"username": "alice"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=5,
    )
    assert reset.status_code == 409
    assert reset.json()["detail"] == {"code": "USER_INTERACTION_BUSY", "retryable": True}

    blocked_chat = websocket.create_connection(ws_url + "/chat_ws", timeout=5, http_proxy_host=None)
    _authenticate(blocked_chat, token)
    error = json.loads(blocked_chat.recv())
    assert error["type"] == "error"
    assert error["payload"]["code"] == "INTERACTION_FINALIZING"
    assert error["payload"]["retryable"] is True
    blocked_chat.close()

    blocked_call = websocket.create_connection(ws_url + "/call_ws", timeout=5, http_proxy_host=None)
    _authenticate(blocked_call, token)
    _control(
        blocked_call,
        {
            "protocol": "call.v1",
            "type": "call.start",
            "seq": 1,
            "client_request_id": "finalizing-call-blocked",
            "character_id": "luotianyi",
            "audio": {"encoding": "pcm_s16le", "sample_rate": 16000, "channels": 1},
        },
    )
    error = _receive_until(blocked_call, "error")
    assert error["code"] == "INTERACTION_FINALIZING" and error["retryable"] is True
    blocked_call.close()

    assert http.post(url + "/test/settlement_write/release", timeout=5).ok
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        restored = websocket.create_connection(ws_url + "/chat_ws", timeout=5, http_proxy_host=None)
        _authenticate(restored, token)
        event = json.loads(restored.recv())
        if event.get("type") == "chat.ready":
            break
        assert event["type"] == "error"
        assert event["payload"]["code"] == "INTERACTION_FINALIZING"
        assert event["payload"]["retryable"] is True
        restored.close()
        time.sleep(0.05)
    else:
        raise AssertionError("chat admission did not recover after finalization")
    restored.send(
        json.dumps(
            {
                "protocol": "call.v1",
                "type": "call.switch_prepare",
                "client_request_id": "finalizing-call-2",
                "character_id": "luotianyi",
            }
        )
    )
    assert _receive_chat_switch_ready(restored)["type"] == "call.switch_ready"
    restored.close()

    second = websocket.create_connection(ws_url + "/call_ws", timeout=5, http_proxy_host=None)
    _authenticate(second, token)
    second_call_id = _start_call(second, "finalizing-call-2")
    assert second_call_id != first_call_id
    _hangup(second, second_call_id)
    second.close()


def test_successful_call_loopback_preserves_privacy_and_reset_credentials(
    successful_call_server,
):
    url, http, root = successful_call_server
    assert http.get(url + "/test/evidence", timeout=5).json()["call_transport_available"] is True
    password = "offline-password"
    encrypted = _encrypted_password(http, url, password)
    assert http.post(
        url + "/auth/register",
        json={"username": "alice", "password": encrypted, "invite_code": "invite"},
        timeout=10,
    ).ok
    login = http.post(
        url + "/auth/login",
        json={
            "username": "alice",
            "password": _encrypted_password(http, url, password),
        },
        timeout=10,
    )
    assert login.ok
    token = login.json()["message_token"]
    ws_url = "ws" + url[4:]

    chat = websocket.create_connection(ws_url + "/chat_ws", timeout=5, http_proxy_host=None)
    try:
        _authenticate(chat, token)
        chat.send(
            json.dumps(
                {
                    "protocol": "call.v1",
                    "type": "call.switch_prepare",
                    "client_request_id": "request-1",
                    "character_id": "luotianyi",
                }
            )
        )
        assert _receive_chat_switch_ready(chat)["type"] == "call.switch_ready"
    finally:
        chat.close()

    call = websocket.create_connection(ws_url + "/call_ws", timeout=5, http_proxy_host=None)
    try:
        _authenticate(call, token)
        _control(
            call,
            {
                "protocol": "call.v1",
                "type": "call.start",
                "seq": 1,
                "client_request_id": "request-1",
                "character_id": "luotianyi",
                "audio": {"encoding": "pcm_s16le", "sample_rate": 16000, "channels": 1},
            },
        )
        preparing = _receive_until(call, "call.state")
        call_id = preparing["call_id"]
        ack = _receive_until(call, "ack")
        assert ack["ack_seq"] == 1
        active = _receive_until(call, "call.active")
        assert active["call_id"] == call_id
        client_pcm = b"\x10\x00\x20\x00"
        call.send_binary(
            BinaryAudioFrameCodec().encode(
                WireAudioFrame(
                    version=VERSION,
                    route=CALL_ROUTE,
                    flags=0,
                    stream_id=0,
                    seq=2,
                    payload=client_pcm,
                )
            )
        )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            provider_audio = http.get(url + "/test/evidence", timeout=5).json()["provider_audio"]
            frames = next(
                (item["frames"] for item in provider_audio if item["call_id"] == call_id),
                [],
            )
            if frames:
                break
            time.sleep(0.05)
        assert frames == [
            {
                "payload": client_pcm.hex(),
                "sequence": 1,
                "encoding": "pcm_s16le",
                "sample_rate": 16000,
                "channels": 1,
            }
        ]
        opening = _receive_until(call, "audio.stream_started")
        assert isinstance(call.recv(), bytes)
        _complete(call, call_id, 3, opening)
        assert http.post(url + f"/test/provider/{call_id}/turn", timeout=5).ok
        provisional = _receive_until(call, "audio.stream_started")
        assert "recall-ack" in provisional["response_id"]
        assert isinstance(call.recv(), bytes)
        _complete(call, call_id, 4, provisional)
        formal = _receive_until(call, "audio.stream_started")
        assert "turn-1" in formal["response_id"]

        started = time.monotonic()
        call.close()
        resumed = websocket.create_connection(ws_url + "/call_ws", timeout=5, http_proxy_host=None)
        try:
            _authenticate(resumed, token)
            _control(
                resumed,
                {
                    "protocol": "call.v1",
                    "type": "call.resume",
                    "call_id": call_id,
                    "character_id": "luotianyi",
                    "last_contiguous_server_seq": 0,
                },
            )
            assert _receive_until(resumed, "call.resumed")["call_id"] == call_id
            assert time.monotonic() - started < 3
            assert http.post(url + f"/test/provider/{call_id}/interrupt", timeout=5).ok
            stopped = _receive_until(resumed, "playback.stop")
            assert stopped["response_id"] == formal["response_id"]
            _control(
                resumed,
                {
                    "protocol": "call.v1",
                    "type": "playback.stopped",
                    "seq": 5,
                    "call_id": call_id,
                    "response_id": formal["response_id"],
                    "stop_seq": stopped["seq"],
                },
            )
            _control(
                resumed,
                {
                    "protocol": "call.v1",
                    "type": "call.hangup",
                    "seq": 6,
                    "call_id": call_id,
                    "reason": "user_hangup",
                },
            )
            ended = _receive_until(resumed, "call.ended", timeout=10)
            assert ended["end_reason"] == "user_hangup"
        finally:
            resumed.close()
    finally:
        call.close()

    deadline = time.monotonic() + 10
    history = None
    while time.monotonic() < deadline:
        response = http.get(
            url + "/history",
            params={"username": "alice", "count": 10},
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        assert response.ok
        history = response.json()["history"]
        if any(item["type"] == "call" for item in history):
            break
        time.sleep(0.05)
    call_history = next(item for item in history if item["type"] == "call")
    assert call_history["content"].startswith("[语音通话] ")
    assert "用户与角色讨论" not in call_history["content"]

    reset = http.post(
        url + "/user/data/reset",
        json={"username": "alice"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    assert reset.ok, reset.text
    time.sleep(0.2)
    assert http.get(url + "/test/reset_counts", timeout=5).json() == {
        "call_sessions": 0,
        "conversations": 0,
        "maintenance_batches": 0,
        "memories": 0,
        "profile": "",
    }
    relogin = http.post(
        url + "/auth/login",
        json={
            "username": "alice",
            "password": _encrypted_password(http, url, password),
        },
        timeout=10,
    )
    assert relogin.ok
    persisted = (root / "db" / "calls.sqlite").read_bytes()
    logs = _process_output(root / "stdout.log", root / "stderr.log")
    for forbidden in ("你还记得我喜欢什么吗", "用户喜欢音乐", "AQIDBA=="):
        assert forbidden.encode("utf-8") not in persisted
        assert forbidden not in logs
