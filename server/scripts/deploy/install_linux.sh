#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
server_dir=$(pwd -P)
if [[ $(uname -s) != Linux || $(uname -m) != x86_64 || $EUID == 0 ]]; then
    echo "请在 Linux x86_64 上以服务运行账号执行安装脚本。" >&2
    exit 1
fi
nvidia-smi
umask 077
runtime_dir="${AGENTLUO_RUNTIME_DIR:-$server_dir/.runtime}"
if [[ "$runtime_dir" != /* ]]; then runtime_dir="$server_dir/$runtime_dir"; fi
mkdir -p "$runtime_dir"
exec 9>"$runtime_dir/server.lock"
flock -n 9 || { echo "请等待安装结束或停止服务后重试。" >&2; exit 1; }

export UV_PROJECT_ENVIRONMENT="$server_dir/.venv"
export UV_LINK_MODE=copy
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$runtime_dir/browsers}"
uv python install 3.10.22
uv sync --project scripts/deploy --python 3.10.22 --locked --no-dev
uv pip check --python .venv/bin/python
.venv/bin/python -m playwright install --with-deps chromium
ffmpeg -nostdin -v error -f lavfi -i sine=duration=0.1 -f mp3 pipe:1 >/dev/null
.venv/bin/python - <<'PY'
import librosa
import numpy as np
import torch
from playwright.sync_api import sync_playwright

x = torch.ones((2, 2), device="cuda")
assert (x @ x).sum().item() == 8
print("CUDA 运算通过：", torch.cuda.get_device_name())
samples = librosa.resample(np.ones(16000, dtype=np.float32), orig_sr=16000, target_sr=8000)
assert len(samples) == 8000
print("音频重采样通过")
with sync_playwright() as playwright:
    with playwright.chromium.launch() as browser:
        page = browser.new_page()
        page.set_content("<title>AgentLuo</title>")
        assert page.title() == "AgentLuo"
print("Chromium 页面渲染通过")
PY
