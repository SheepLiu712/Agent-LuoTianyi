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

# 服务端 AgentPresentationState 的实际取值（真源 server/src/domain/stage/output.py）。
# N6 的历史缺陷是驱动等待服务端从不发射的 "listening"；这里只做取值合法性校验，不把它当硬性前置条件，
# 因为服务端仅在计划以 StartThinking 打头时才发 thinking（记忆确认等路径不发）。
ALLOWED_AGENT_STATES = {"thinking", "waiting"}


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
    events = session.read_events()
    before_seq = events[-1]["seq"] if events else 0
    result = session.send_voice(voice_path, upload_id=str(uuid.uuid4()), ack_timeout=15)
    completed = session.wait_for_event("reply_completed", after_seq=before_seq, timeout=150)
    observed_states = {event["value"] for event in session.read_events(after_seq=before_seq, kind="agent_state")}
    unexpected = observed_states - ALLOWED_AGENT_STATES
    if unexpected:
        raise AssertionError(f"unexpected agent_state values: {sorted(unexpected)}")
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
