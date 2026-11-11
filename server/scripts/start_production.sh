#!/usr/bin/env bash
set -euo pipefail
exec /bin/bash "$(dirname -- "${BASH_SOURCE[0]}")/deploy/startup/start_linux.sh" "$@"
