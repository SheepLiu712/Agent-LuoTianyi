#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.."
umask 077
server_dir=$(pwd -P)
python_bin="${AGENTLUO_PYTHON:-$server_dir/.venv/bin/python}"
export AGENTLUO_RUNTIME_DIR
AGENTLUO_RUNTIME_DIR=$("$python_bin" -c 'from src.utils.server_paths import ServerPaths; print(ServerPaths.from_environment().runtime_dir)')
mkdir -p "$AGENTLUO_RUNTIME_DIR"
export PYTHONUNBUFFERED=1
export PYTHONUTF8=1
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$AGENTLUO_RUNTIME_DIR/browsers}"
export NO_PROXY="localhost,127.0.0.1,::1,api.siliconflow.cn,dashscope.aliyuncs.com,restapi.amap.com,vcpedia.cn${NO_PROXY:+,$NO_PROXY}${no_proxy:+,$no_proxy}"
export no_proxy="$NO_PROXY"
exec 9>"$AGENTLUO_RUNTIME_DIR/server.lock"
flock -n 9 || { echo "当前部署正在安装或运行。" >&2; exit 1; }
exec "$python_bin" "$server_dir/server_main.py" "$@"
