"""S4 音频失败分类驱动：AUDIO_EPHEMERAL / AUDIO_FILE_MISSING / AUDIO_FORMAT_INVALID / AUDIO_REPLY_NOT_FOUND。

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
OUT = Path(os.environ.get("CLI_E2E_OUT", "r9-out.jsonl"))
TTS_DIR = CLIENT_DIR / "temp" / "tts_output"
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"

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
        (record.get("error") or {}).get("code", ""),
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

    # 1) 临时回复（触摸反射）重放 -> AUDIO_EPHEMERAL
    ephemeral = None
    for _ in range(3):
        send("touch.send", {"touch_area": "头", "ack_timeout": 10})
        receive()
        send("reply.wait", {"timeout": 30})
        record = receive()
        data = record.get("data") or {}
        if data.get("is_ephemeral"):
            ephemeral = data
            break
    if ephemeral is not None:
        send("audio.replay", {"reply_uuid": ephemeral["reply_uuid"]})
        receive()
    else:
        print("no ephemeral reply captured; skipped AUDIO_EPHEMERAL", flush=True)

    # 2) 文本回复：基线重放 -> 删除文件 -> 覆盖垃圾字节
    send(
        "chat.send_text",
        {"text": "用一句话告诉我你最喜欢的一首天依的歌吧～", "ack_timeout": 15},
    )
    receive()

    target = None
    for _ in range(3):
        send("reply.wait", {"timeout": 60})
        record = receive()
        data = record.get("data") or {}
        if (data.get("audio") or {}).get("reference"):
            target = data
            break

    if target is None:
        print("no reply with saved audio; skipped file-based checks", flush=True)
    else:
        reply_uuid = target["reply_uuid"]
        reference = target["audio"]["reference"]

        send("audio.replay", {"reply_uuid": reply_uuid})
        receive()

        wav_path = TTS_DIR / reference
        wav_path.unlink(missing_ok=True)
        send("audio.replay", {"reply_uuid": reply_uuid})
        receive()

        wav_path.write_bytes(b"this is not a wav file")
        send("audio.replay", {"reply_uuid": reply_uuid})
        receive()

    # 3) 未知 UUID -> AUDIO_REPLY_NOT_FOUND
    send("audio.replay", {"reply_uuid": UNKNOWN_UUID})
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
