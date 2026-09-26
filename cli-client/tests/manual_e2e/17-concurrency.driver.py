"""并发回复关联观察驱动：连续发送两条文本后等待三条回复，记录到达顺序与内容归属。

用法（在 cli-client/ 目录运行，或设置 CLI_E2E_ROOT）：
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

CLI_ROOT = Path(os.environ.get("CLI_E2E_ROOT", os.getcwd()))
if not (CLI_ROOT / "cli.py").exists():
    raise SystemExit(f"cli.py not found in {CLI_ROOT}; set CLI_E2E_ROOT")

if not os.environ.get("CLI_E2E_PASSWORD"):
    raise SystemExit("CLI_E2E_PASSWORD is not set")

BASE_URL = os.environ.get("CLI_E2E_BASE_URL")
if not BASE_URL:
    raise SystemExit("CLI_E2E_BASE_URL is not set")
USERNAME = os.environ.get("CLI_E2E_USER", "cli_e2e_user")
OUT = Path(os.environ.get("CLI_E2E_OUT", "r10-out.jsonl"))

proc = subprocess.Popen(
    [sys.executable, "cli.py"],
    cwd=CLI_ROOT,
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
    print(
        "RECORD:",
        record["action"],
        record["status"],
        (record.get("data") or {}).get("text", "")[:40],
        flush=True,
    )
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

    send(
        "chat.send_text",
        {"text": "请用一句话回答：你最喜欢的水果是什么？", "ack_timeout": 15},
    )
    receive()
    send(
        "chat.send_text",
        {"text": "请用一句话回答：你最喜欢的颜色是什么？", "ack_timeout": 15},
    )
    receive()

    for _ in range(3):
        send("reply.wait", {"timeout": 90})
        receive()
finally:
    proc.stdin.close()
    proc.wait(timeout=60)

print("child exit:", proc.returncode, flush=True)

OUT.write_text(
    "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
    encoding="utf-8",
    newline="\n",
)
print("written", OUT, flush=True)
