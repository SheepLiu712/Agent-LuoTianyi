"""AC-27: real loopback HTTP/WS and CLI driver, deterministic model providers."""

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest
import requests
from support.audio_samples import recorded_aac_bytes


@pytest.fixture
def offline_voice_server(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[4]
    monkeypatch.syspath_prepend(str(repo / "cli-client"))
    root = tmp_path / "server"
    root.mkdir()
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(repo / "server"), str(repo / "server/tests"), env.get("PYTHONPATH", "")])
    env["PYTHONIOENCODING"] = "utf-8"
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(key, None)
    log_path = root / "server.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "support.voice_offline_server", str(root)],
            cwd=root,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        http = requests.Session()
        http.trust_env = False
        url = None
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                assert process.poll() is None, log_path.read_text(encoding="utf-8")
                address = root / "address.json"
                if address.exists():
                    url = json.loads(address.read_text(encoding="utf-8"))["url"]
                    try:
                        if http.get(url + "/test/evidence", timeout=0.5).status_code == 200:
                            break
                    except requests.RequestException:
                        pass
                time.sleep(0.05)
            else:
                pytest.fail("offline server readiness timed out\n" + log_path.read_text(encoding="utf-8"))
            yield url, http, root
        finally:
            if process.poll() is None:
                if url:
                    try:
                        http.post(url + "/test/stop", timeout=2)
                    except requests.RequestException:
                        pass
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            http.close()
            assert process.returncode == 0, log_path.read_text(encoding="utf-8")


def test_voice_cli_real_ws_reply_history_and_authenticated_download(offline_voice_server, tmp_path):
    from cli_client.network.network_client import NetworkClient
    from cli_client.session import HeadlessSession, ReplyTimeoutError

    url, http, root = offline_voice_server
    source = tmp_path / "android.m4a"
    # Force multiple real chunks without changing media offsets or duration.
    padding = b"\0" * 100_000
    data = recorded_aac_bytes(android_metadata=True) + (len(padding) + 8).to_bytes(4, "big") + b"free" + padding
    source.write_bytes(data)
    network = NetworkClient(url)
    network.session.trust_env = False
    client = HeadlessSession(url, network_client=network, audio_output_dir=tmp_path / "client-audio")
    acknowledgements = []
    original = network.ws_transport.submit_user_voice

    def observe(*args, **kwargs):
        ack = original(*args, **kwargs)
        acknowledgements.append((args[0], ack))
        return ack

    network.ws_transport.submit_user_voice = observe
    try:
        client.connect("alice", "offline-password", timeout=10)
        upload_id = str(uuid4())
        result = client.send_voice(source, upload_id=upload_id, ack_timeout=5)
        listening = client.wait_for_event("agent_state", value="listening", timeout=10)
        thinking = client.wait_for_event("agent_state", value="thinking", timeout=10)
        completed = client.wait_for_event("reply_completed", timeout=10)
        assert listening["seq"] < thinking["seq"] < completed["seq"]
        reply = client.get_reply(completed["data"]["reply_uuid"])
        assert "".join(reply.texts) == "收到你的测试语音了。"
        assert [phase for phase, _ in acknowledgements] == ["begin", "chunk", "chunk", "chunk", "finalize"]
        assert all(ack["ok"] for _, ack in acknowledgements)
        # Retry the entire immutable identity over real WS; no second interpretation/reply.
        assert client.send_voice(source, upload_id=upload_id, ack_timeout=5) == result
        with pytest.raises(ReplyTimeoutError):
            client.wait_for_event("reply_completed", after_seq=completed["seq"], timeout=2)
        client.assert_voice_in_history(result["message_uuid"], 1064)
        assert client.assert_download_sha256(result["message_uuid"], source) == hashlib.sha256(data).hexdigest()
        evidence = http.get(url + "/test/evidence", timeout=5).json()
        assert evidence == {"audio_calls": 1, "reply_calls": 1}
        history = http.get(
            url + "/history",
            params={"username": "alice", "count": 100, "end_index": -1},
            headers={"Authorization": f"Bearer {network.message_token}"},
            timeout=5,
        ).json()
        serialized = json.dumps(history, ensure_ascii=False)
        for internal in ("transcript", "emotion", "sound_description", "understanding_status", "测试语音请求"):
            assert internal not in serialized
        items, _ = client.get_history(count=100, end_index=-1)
        assert len([item for item in items if item.type == "audio"]) == 1
        assert len([item for item in items if item.source == "agent"]) == 1
        check_download_access(http, url, result["message_uuid"], network.message_token)
    finally:
        client.close()


def check_download_access(http, url, message_uuid, owner_token):
    from cli_client.network.network_client import NetworkClient

    path = url + "/media/audio/" + message_uuid
    owned = http.get(path, headers={"Authorization": f"Bearer {owner_token}"}, timeout=5)
    assert owned.status_code == 200
    assert owned.headers["content-type"] == "audio/mp4"
    assert len(owned.content) == int(owned.headers["content-length"])
    assert http.get(path, timeout=5).status_code == 401
    assert http.get(path, headers={"Authorization": "Bearer invalid"}, timeout=5).status_code == 401
    other = NetworkClient(url)
    other.session.trust_env = False
    try:
        assert other.login("bob", "offline-password")[0]
        assert http.get(path, headers={"Authorization": f"Bearer {other.message_token}"}, timeout=5).status_code == 404
        response = http.post(url + "/test/delete-media/alice", timeout=5)
        assert response.status_code == 200, response.text
        assert http.get(path, headers={"Authorization": f"Bearer {owner_token}"}, timeout=5).status_code == 404
        assert http.post(url + "/test/delete-media/alice", timeout=5).status_code == 200
    finally:
        other.ws_transport.stop()
        other.session.close()
