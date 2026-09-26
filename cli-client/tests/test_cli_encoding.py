import json
import subprocess
import sys
from pathlib import Path

CLIENT_DIR = Path(__file__).resolve().parents[1]


def test_cli_stdio_is_utf8_for_redirected_streams():
    """重定向/管道场景下 JSONL 必须为 UTF-8（Windows 默认本地编码会损坏中文）。"""
    payload = json.dumps({"action": "中文测试"}, ensure_ascii=False).encode("utf-8")

    result = subprocess.run(
        [sys.executable, "cli.py"],
        cwd=CLIENT_DIR,
        input=payload + b"\n",
        capture_output=True,
        timeout=60,
    )

    assert result.returncode == 3
    stdout_text = result.stdout.decode("utf-8")
    lines = [line for line in stdout_text.splitlines() if line.strip()]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["error"]["code"] == "UNKNOWN_ACTION"
    assert "中文测试" in record["error"]["message"]
    result.stderr.decode("utf-8")
