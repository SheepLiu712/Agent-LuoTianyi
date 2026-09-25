from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parents[3]


def test_agent_refactor_architecture_boundaries() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_architecture_boundaries.py"],
        cwd=SERVER_ROOT,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        text=True,
    )

    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    assert result.returncode == 0, output
