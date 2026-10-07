"""Keep the standalone client's image pipeline aligned with the desktop client."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CLIENT_ROOT = REPO_ROOT / "client"
CLI_ROOT = REPO_ROOT / "cli-client"


def _desktop_source(name: str) -> str:
    path = CLIENT_ROOT / "src" / "utils" / name
    if not path.exists():
        pytest.skip("desktop client tree is not available")
    return path.read_text(encoding="utf-8")


def _cli_source(name: str) -> str:
    return (CLI_ROOT / "cli_client" / "utils" / name).read_text(encoding="utf-8")


def test_compression_module_matches_desktop_source():
    assert _cli_source("image_compression.py") == _desktop_source("image_compression.py")


def test_encoding_pipeline_matches_desktop_source_except_module_docstring():
    desktop_lines = _desktop_source("image_encoding.py").splitlines()
    cli_lines = _cli_source("image_encoding.py").splitlines()
    assert cli_lines[0] != desktop_lines[0]
    assert cli_lines[1:] == desktop_lines[1:]
