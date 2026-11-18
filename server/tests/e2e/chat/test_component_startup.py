"""组件全关闭的真实生产生命周期回环验收；只外部模型生成接口离线。"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest
import requests
import websocket
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


def _child_environment(server):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join((str(server), str(server / "tests")))
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for key in tuple(env):
        if key.upper().endswith("_PROXY") or key in {
            "QWEN_API_KEY",
            "SILICONFLOW_API_KEY",
            "OPENAI_API_KEY",
            "AMAP_KEY",
        }:
            env.pop(key, None)
    return env


@pytest.fixture
def component_server(tmp_path):
    server = Path(__file__).resolve().parents[3]
    root = tmp_path / "component-instance"
    root.mkdir()
    env = _child_environment(server)
    http = requests.Session()
    http.trust_env = False
    started = time.monotonic()
    log_path = root / "server.log"
    url = None
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-B", "-m", "support.component_startup_offline_server", str(root)],
            cwd=root,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = started + 45
            while time.monotonic() < deadline:
                assert process.poll() is None, log_path.read_text(encoding="utf-8")
                address = root / "address.json"
                if address.exists():
                    url = json.loads(address.read_text(encoding="utf-8"))["url"]
                    try:
                        evidence = http.get(url + "/test/evidence", timeout=0.5)
                        if evidence.ok and evidence.json().get("running"):
                            assert http.get(url + "/auth/public_key", timeout=2).ok
                            break
                    except requests.RequestException:
                        pass
                time.sleep(0.05)
            else:
                pytest.fail("isolated production startup exceeded45s\n" + log_path.read_text(encoding="utf-8"))
            yield url, http, root
        finally:
            if process.poll() is None and url is not None:
                try:
                    http.post(url + "/test/stop", timeout=2)
                except requests.RequestException:
                    pass
            if process.poll() is None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            http.close()
            assert process.returncode == 0, log_path.read_text(encoding="utf-8")
            assert json.loads((root / "closed.json").read_text(encoding="utf-8"))["closed"] is True
            assert time.monotonic() - started < 90


def admin_login(http, url, root):
    password = "isolated-admin-password"
    token = (root / "config/admin_setup_token.txt").read_text(encoding="utf-8").strip()
    response = http.post(
        url + "/admin/api/admin-auth/setup", json={"setup_token": token, "password": password}, timeout=5
    )
    assert response.status_code == 200
    response = http.post(url + "/admin/api/admin-auth/login", json={"password": password}, timeout=5)
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["token"]}


def encrypted_password(http, url, value):
    public = http.get(url + "/auth/public_key", timeout=5).json()["public_key"]
    key = serialization.load_pem_public_key(public.encode())
    return base64.b64encode(
        key.encrypt(
            value.encode(),
            padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
        )
    ).decode()


def register_login(http, url, headers, username):
    code = http.post(url + "/admin/api/invite-codes/generate", headers=headers, json={"count": 1}, timeout=5)
    assert code.status_code == 200
    value = code.json()["codes"][0]
    invite = value if isinstance(value, str) else value["code"]
    password = "isolated-user-password"
    register = http.post(
        url + "/auth/register",
        json={
            "username": username,
            "password": encrypted_password(http, url, password),
            "invite_code": invite,
        },
        timeout=5,
    )
    assert register.status_code == 200
    login = http.post(
        url + "/auth/login",
        json={
            "username": username,
            "password": encrypted_password(http, url, password),
        },
        timeout=5,
    )
    assert login.status_code == 200
    return login.json()["message_token"]


def connect_chat(url, username, token):
    ws = websocket.create_connection("ws" + url[4:] + "/chat_ws", timeout=10, http_proxy_host=None)
    assert json.loads(ws.recv())["type"] == "system_ready"
    ws.send(
        json.dumps({"type": "user_auth", "client_msg_id": "auth", "payload": {"username": username, "token": token}})
    )
    assert json.loads(ws.recv())["type"] == "auth_ok"
    while json.loads(ws.recv())["type"] != "chat.ready":
        pass
    return ws


def send_text(ws, text):
    ws.send(json.dumps({"type": "user_text", "client_msg_id": str(uuid4()), "payload": {"message": text}}))
    packets = []
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        event = json.loads(ws.recv())
        if event.get("type") == "agent_message":
            packet = event["payload"]
            packets.append(packet)
            if packet["is_final_package"]:
                assert packet["audio_error"] is False
                assert all(p["audio"] == "" for p in packets)
                assert sum(p["is_final_package"] for p in packets) == 1
                return "".join(p["text"] for p in packets), packets[0]["uuid"]
    raise AssertionError("reply did not finish")


def upload_voice(ws, data):
    upload_id = str(uuid4())
    messages = [
        {
            "phase": "begin",
            "upload_id": upload_id,
            "mime_type": "audio/mp4",
            "container": "m4a",
            "codec": "aac_lc",
            "byte_length": len(data),
            "total_chunks": 1,
        },
        {"phase": "chunk", "upload_id": upload_id, "chunk_index": 0, "audio_base64": base64.b64encode(data).decode()},
        {"phase": "finalize", "upload_id": upload_id},
    ]
    result = None
    for payload in messages:
        client_id = str(uuid4())
        ws.send(json.dumps({"type": "user_voice", "client_msg_id": client_id, "payload": payload}))
        while True:
            event = json.loads(ws.recv())
            if event.get("type") == "server_ack" and event.get("reply_to") == client_id:
                ack = event["payload"]
                assert ack["ok"] is True
                result = ack
                break
    # finalize ACK只确认接纳，等实际音频理解/回复终态后才证明对话媒体已持久化。
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        event = json.loads(ws.recv())
        if event.get("type") == "agent_message" and event["payload"]["is_final_package"]:
            assert event["payload"]["audio_error"] is False
            return result
    raise AssertionError("voice upload accepted but dialogue did not finish")


def test_production_component_disabled_register_login_ws_history(component_server):
    url, http, root = component_server
    headers = admin_login(http, url, root)
    token = register_login(http, url, headers, "spec412_user")
    ws = connect_chat(url, "spec412_user", token)
    try:
        replies = [send_text(ws, text)[0] for text in ("请只回复：核心链路412", "请只回复：第二条")]
        assert replies == ["核心链路412", "第二条回复"]
        from support.audio_samples import recorded_aac_bytes

        audio = recorded_aac_bytes()
        uploaded = upload_voice(ws, audio)
        voice_id = uploaded["message_uuid"]
    finally:
        ws.close()
    history = http.get(
        url + "/history",
        params={"username": "spec412_user", "count": 100, "end_index": -1},
        headers={"Authorization": "Bearer " + token},
        timeout=5,
    )
    assert history.status_code == 200
    content = json.dumps(history.json(), ensure_ascii=False)
    for text in replies + ["请只回复：核心链路412", "请只回复：第二条"]:
        assert text in content
    download = url + "/media/audio/" + voice_id
    owner = http.get(download, headers={"Authorization": "Bearer " + token}, timeout=5)
    assert owner.status_code == 200 and owner.content == audio
    assert http.get(download, timeout=5).status_code == 401
    assert http.get(download, headers={"Authorization": "Bearer invalid"}, timeout=5).status_code == 401
    other = register_login(http, url, headers, "spec412_other")
    assert http.get(download, headers={"Authorization": "Bearer " + other}, timeout=5).status_code == 404
    evidence = http.get(url + "/test/evidence", timeout=5).json()
    assert evidence["runtime_type"] == "ServerRuntime"
    assert (
        evidence["world_task_count"]
        == evidence["world_interval_count"]
        == evidence["world_daily_count"]
        == evidence["world_execution_count"]
        == 0
    )
    assert evidence["speaking_enabled"] is False and evidence["vector_enabled"] is False
    assert not any(evidence["resource_attempts"].values())
    assert evidence["prompt_count"] > 0
    assert "FindMatchingEvent" in evidence["llm_module_names"]
    assert any("skill.reply.generate" in name for name in evidence["llm_module_names"])
    print(
        "A5_OFFLINE_PRODUCTION_LOOPBACK=PASS; text/terminal/history/world/disabled-resources; "
        "not real provider/benchmark"
    )
