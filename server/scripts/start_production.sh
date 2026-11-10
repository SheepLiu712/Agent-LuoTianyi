#!/usr/bin/env bash
set -euo pipefail
exec /bin/bash "$(dirname -- "${BASH_SOURCE[0]}")/deploy/start_linux.sh" "$@"
