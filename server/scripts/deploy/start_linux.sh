#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
umask 077
mkdir -p .runtime
export PYTHONUNBUFFERED=1
export PYTHONUTF8=1
export PLAYWRIGHT_BROWSERS_PATH="$(pwd -P)/.runtime/browsers"
export NO_PROXY="localhost,127.0.0.1,::1,api.siliconflow.cn,dashscope.aliyuncs.com,restapi.amap.com,vcpedia.cn${NO_PROXY:+,$NO_PROXY}${no_proxy:+,$no_proxy}"
export no_proxy="$NO_PROXY"
exec 9>.runtime/server.lock
flock -n 9 || { echo "当前部署正在安装或运行。" >&2; exit 1; }
exec .venv/bin/python server_main.py
