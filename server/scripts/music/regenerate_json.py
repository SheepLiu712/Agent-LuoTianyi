import sys
import subprocess
import os
from pathlib import Path
import argparse

songlearner_dir = r"src\plugins\music\song_learner"
runner = Path(songlearner_dir) / "run_song_workflow.py"
print(runner)

parser = argparse.ArgumentParser(description="测试运行 run_song_workflow.py")
parser.add_argument("song_name", help="歌曲名，例如：万古生香")
args = parser.parse_args()
song_name = args.song_name

SONGELEARNER_TIMEOUT = 20 * 60  # 20分钟
try:
    proc = subprocess.run(
        [sys.executable, str(runner), song_name],
        # cwd=str(songlearner_dir),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=SONGELEARNER_TIMEOUT,
        env={
            **os.environ,
            "QWEN_API_KEY": os.environ.get("QWEN_API_KEY", ""),
            "SILICONFLOW_API_KEY": os.environ.get("SILICONFLOW_API_KEY", ""),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        },
    )
except subprocess.TimeoutExpired:
    raise TimeoutError(f"歌曲处理超时（超过 {SONGELEARNER_TIMEOUT} 秒）")

if proc.returncode != 0:
    print(f"运行失败，返回码: {proc.returncode}")
    print("标准输出:")
    print(proc.stdout)
    print("标准错误:")
    print(proc.stderr)