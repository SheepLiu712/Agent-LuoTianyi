from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile


SERVER_ROOT = Path(__file__).resolve().parents[3]


def test_wheel_contains_regular_and_namespace_packages(tmp_path: Path) -> None:
    source = tmp_path / "server"
    source.mkdir()
    for name in ("pyproject.toml", "README.md", "server_main.py"):
        shutil.copy2(SERVER_ROOT / name, source / name)
    shutil.copytree(
        SERVER_ROOT / "src",
        source / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "temp"),
    )

    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", "dist"],
        cwd=source,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        text=True,
    )
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    assert result.returncode == 0, output

    wheels = tuple((source / "dist").glob("agentluo_server-*.whl"))
    assert len(wheels) == 1, output
    with ZipFile(wheels[0]) as wheel:
        members = set(wheel.namelist())

    assert {
        "server_main.py",
        "src/agent/facade.py",
        "src/agent/skills/adapters/memory/facade.py",
        "src/agent/skills/cognitive/response_generation.py",
        "src/infrastructure/song_knowledge/database.py",
        "src/world/get_new_songs/task.py",
        "src/world/learn_sing_songs/task.py",
        "src/world/types/task_result.py",
    } <= members
    assert not any(
        member.startswith(("src/chat_session/", "src/subconscious/", "src/legacy/"))
        for member in members
    )
