"""Measure chat thinking deadlines through the CLI's public JSONL interface.

Run from cli-client/ after creating an isolated CLI auto-login file. Set
CLI_E2E_CREDENTIAL_FILE and CLI_E2E_IMAGE to override their default paths.
Results are written under cli-client/temp/cli_acceptance_timing/.
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

CLI_ROOT = Path(__file__).resolve().parents[2]
CREDENTIAL_FILE = os.environ.get("CLI_E2E_CREDENTIAL_FILE", "temp/cli_auto_login.json")
IMAGE_PATH = Path(os.environ.get("CLI_E2E_IMAGE", str(Path(os.environ.get("TEMP", ".")) / "cli_e2e_image.png")))
OUTPUT_DIR = CLI_ROOT / "temp" / "cli_acceptance_timing"


def milliseconds(timestamp):
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp() * 1000


def run_case(source, behavior):
    name = f"{source}-{behavior}"
    process = subprocess.Popen(
        [sys.executable, "cli.py"],
        cwd=CLI_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    records = []

    def action(name, **params):
        process.stdin.write(json.dumps({"action": name, "params": params}, ensure_ascii=False) + "\n")
        process.stdin.flush()
        record = json.loads(process.stdout.readline())
        records.append(record)
        if record["status"] != "passed":
            raise RuntimeError(f"{name}: {record.get('error')}")
        return record

    try:
        action("session.auto_connect", credential_file=CREDENTIAL_FILE, timeout=20)
        before = action("events.read")
        baseline_seq = max((item["seq"] for item in before["data"]["events"]), default=0)
        if source == "text":
            sent = action("chat.send_text", text=f"CLI 时序验收 {name}：请简短回复。", ack_timeout=15)
        else:
            sent = action("image.send", path=str(IMAGE_PATH), ack_timeout=15)
        reference = sent
        if behavior == "typing-positive":
            reference = action("chat.send_typing", text_length=3, ack_timeout=15)
        elif behavior == "typing-zero":
            reference = action("chat.send_typing", text_length=0, ack_timeout=15)
        elif behavior == "second-message":
            reference = action("chat.send_text", text=f"CLI 时序验收 {name}：这是后发消息。", ack_timeout=15)
        elif behavior == "second-image":
            reference = action("image.send", path=str(IMAGE_PATH), ack_timeout=15)
        elif behavior == "image-select":
            reference = action("image.select", path=str(IMAGE_PATH), ack_timeout=15)
        elif behavior == "image-cancel":
            action("image.select", path=str(IMAGE_PATH), ack_timeout=15)
            reference = action("image.cancel", ack_timeout=15)
        thinking = action("events.wait", kind="agent_state", value="thinking", after_seq=baseline_seq, timeout=90)
        thinking_event = thinking["data"]["event"]
        delay = (thinking_event["timestamp_ms"] - milliseconds(reference["timestamp"])) / 1000
        waiting = action(
            "events.wait", kind="agent_state", value="waiting", after_seq=thinking_event["seq"], timeout=180
        )
        action("events.wait", kind="reply_completed", after_seq=thinking_event["seq"], timeout=180)
        completed = action("events.read", after_seq=baseline_seq, kind="reply_completed")
        result = {
            "case": name,
            "thinking_after_reference_seconds": round(delay, 3),
            "reply_count": completed["data"]["count"],
            "waiting_observed": waiting["data"]["event"]["value"] == "waiting",
        }
    except Exception as exc:
        result = {"case": name, "error": str(exc)}
    finally:
        try:
            action("session.close")
        except Exception:
            pass
        process.stdin.close()
        process.wait(timeout=10)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / f"{name}.jsonl").write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records),
            encoding="utf-8",
        )
    return result


def main():
    if not IMAGE_PATH.is_file():
        raise SystemExit("CLI_E2E_IMAGE does not name an image file")
    selected = os.environ.get("CLI_E2E_CASE")
    for source in ("text", "image"):
        for behavior in (
            "baseline",
            "typing-positive",
            "typing-zero",
            "second-message",
            "second-image",
            "image-select",
            "image-cancel",
        ):
            if selected and selected != f"{source}-{behavior}":
                continue
            print(json.dumps(run_case(source, behavior), ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
