"""AC-27 real-server voice driver using HeadlessSession directly.

Set CLI_E2E_BASE_URL, CLI_E2E_USER, CLI_E2E_PASSWORD and CLI_E2E_VOICE to
an isolated test server/account and a valid 0.5-30.5 second M4A/AAC-LC file.
"""

import os
import sys
import uuid
from pathlib import Path

CLI_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CLI_ROOT))

from cli_client.session import HeadlessSession  # noqa: E402


def required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is not set")
    return value


base_url = required("CLI_E2E_BASE_URL")
username = required("CLI_E2E_USER")
password = required("CLI_E2E_PASSWORD")
voice_path = Path(required("CLI_E2E_VOICE"))
session = HeadlessSession(base_url)

try:
    session.connect(username, password, timeout=15)
    before_seq = session.read_events()[-1]["seq"] if session.read_events() else 0
    result = session.send_voice(voice_path, upload_id=str(uuid.uuid4()), ack_timeout=15)
    session.wait_for_event("agent_state", after_seq=before_seq, value="listening", timeout=30)
    session.wait_for_event("agent_state", after_seq=before_seq, value="thinking", timeout=90)
    completed = session.wait_for_event("reply_completed", after_seq=before_seq, timeout=150)
    reply = session.get_reply(completed["data"]["reply_uuid"])
    if reply is None:
        raise AssertionError("completed reply is unavailable")
    if not "".join(reply.texts).strip():
        raise AssertionError("agent reply is empty")
    session.assert_voice_in_history(result["message_uuid"], result["duration_ms"])
    digest = session.assert_download_sha256(result["message_uuid"], voice_path)
    print(
        {
            "message_uuid": result["message_uuid"],
            "duration_ms": result["duration_ms"],
            "reply_uuid": reply.uuid,
            "sha256": digest,
        }
    )
except Exception as exc:
    print(f"AC-27 failed: {exc}", file=sys.stderr)
    raise SystemExit(1) from exc
finally:
    session.close()
