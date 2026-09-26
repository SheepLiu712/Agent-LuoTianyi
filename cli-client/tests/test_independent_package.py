"""The CLI can start when only its own source root is importable."""

import json
import subprocess
import sys
from pathlib import Path

CLI_ROOT = Path(__file__).resolve().parents[1]


def test_cli_starts_without_desktop_source_on_python_path(tmp_path):
    program = (
        "import runpy, sys; "
        "from pathlib import Path; "
        "root = Path(sys.argv[1]); "
        "sys.path.insert(0, str(root)); "
        "sys.argv = [str(root / 'cli.py'), '--action', '{\"action\":\"session.status\"}']; "
        "runpy.run_path(sys.argv[0], run_name='__main__')"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", program, str(CLI_ROOT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    record = json.loads(result.stdout)
    assert record["action"] == "session.status"
    assert record["data"] == {"state": "new"}
