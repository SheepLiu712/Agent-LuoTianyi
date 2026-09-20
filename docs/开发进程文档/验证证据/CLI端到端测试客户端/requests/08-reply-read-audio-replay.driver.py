"""动态 UUID 驱动：在单个 CLI 进程内串联 reply.wait -> reply.wait(显式) -> reply.read -> audio.replay。

用法（在 client/ 目录运行，或设置 CLI_E2E_CLIENT_DIR）：
  set CLI_E2E_USER=<username>
  set CLI_E2E_PASSWORD=<password>
  set CLI_E2E_OUT=<输出 JSONL 路径>
  python <本脚本>
"""

import json
import os
import subprocess
import sys
from pathlib import Path

CLIENT_DIR = Path(os.environ.get("CLI_E2E_CLIENT_DIR", os.getcwd()))
if not (CLIENT_DIR / "cli.py").exists():
    raise SystemExit(f"cli.py not found in {CLIENT_DIR}; set CLI_E2E_CLIENT_DIR")

if not os.environ.get("CLI_E2E_PASSWORD"):
    raise SystemExit("CLI_E2E_PASSWORD is not set")

BASE_URL = os.environ.get("CLI_E2E_BASE_URL", "https://www-api.u3493359.nyat.app:11664")
USERNAME = os.environ.get("CLI_E2E_USER", "cli_e2e_user")
OUT = Path(os.environ.get("CLI_E2E_OUT", "r1-out.jsonl"))

proc = subprocess.Popen(
    [sys.executable, "cli.py"],
    cwd=CLIENT_DIR,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
    env=dict(os.environ),
    text=True,
    encoding="utf-8",
)

records = []


def send(action, params=None):
    payload = {"action": action}
    if params is not None:
        payload["params"] = params
    proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
    proc.stdin.flush()


def receive():
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError(f"no record after {len(records)} actions")
    record = json.loads(line)
    records.append(record)
    print("RECORD:", record["action"], record["status"], flush=True)
    return record


try:
    send(
        "session.connect",
        {
            "base_url": BASE_URL,
            "username": USERNAME,
            "password_env": "CLI_E2E_PASSWORD",
            "timeout": 15,
        },
    )
    receive()

    send("session.status")
    receive()

    send(
        "chat.send_text",
        {"text": "最后再确认一次～请用一句话告诉我你现在的心情吧！", "ack_timeout": 15},
    )
    receive()

    send("reply.wait", {"timeout": 150, "non_empty": True})
    wait_record = receive()
    reply_uuid = wait_record["data"]["reply_uuid"]

    send("reply.wait", {"reply_uuid": reply_uuid, "timeout": 10})
    receive()

    send("reply.read", {"reply_uuid": reply_uuid})
    receive()

    send("audio.replay", {"reply_uuid": reply_uuid})
    receive()
finally:
    proc.stdin.close()
    proc.wait(timeout=60)

OUT.write_text(
    "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
    encoding="utf-8",
    newline="\n",
)
print("written", OUT, flush=True)
