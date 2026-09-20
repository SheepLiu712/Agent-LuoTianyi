"""S6 抑制时序驱动：触发 TTS 流式回复，在"服务端音频活跃"窗口内连发触摸直至命中本地抑制。

用法（在 client/ 目录运行，或设置 CLI_E2E_CLIENT_DIR）：
  set CLI_E2E_USER=<username>
  set CLI_E2E_PASSWORD=<password>
  set CLI_E2E_OUT=<输出 JSONL 路径>
  python <本脚本>

预期：回复音频流式期间的部分 touch.send 返回 status="suppressed"、
data={"suppressed": true, "reason": "server_audio_active"}、退出码 0，且不产生协议事件。
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
OUT = Path(os.environ.get("CLI_E2E_OUT", "r8-out.jsonl"))
MAX_TOUCHES = int(os.environ.get("CLI_E2E_MAX_TOUCHES", "200"))
TARGET_SUPPRESSED = 3

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
    print(
        "RECORD:",
        record["action"],
        record["status"],
        record.get("data", {}).get("reason", ""),
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
        {
            "text": "请用三到四句话描述一下你今天的心情和最近喜欢做的事情吧～",
            "ack_timeout": 15,
        },
    )
    receive()

    suppressed = 0
    for _ in range(MAX_TOUCHES):
        send("touch.send", {"touch_area": "头", "ack_timeout": 3})
        record = receive()
        if record["status"] == "suppressed":
            suppressed += 1
            if suppressed >= TARGET_SUPPRESSED:
                break

    print("suppressed count:", suppressed, flush=True)

    send("reply.wait", {"timeout": 30})
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
