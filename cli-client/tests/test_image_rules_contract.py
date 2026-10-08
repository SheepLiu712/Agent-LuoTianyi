"""Keep the standalone client's image limits aligned with the server contract."""

import ast
import json
from pathlib import Path

import pytest

from cli_client.utils import image_rules

SERVER_ROOT = Path(__file__).resolve().parents[2] / "server"


def _server_mime_types() -> set[str]:
    path = SERVER_ROOT / "src" / "infrastructure" / "media" / "image_validation.py"
    if not path.exists():
        pytest.skip("server tree is not available")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mapping = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_FORMAT_MIME" for target in node.targets)
    )
    return set(mapping.values()) | {"image/jpg"}


def test_max_image_bytes_matches_shipped_server_config():
    path = SERVER_ROOT / "config" / "config.json"
    if not path.exists():
        pytest.skip("server tree is not available")
    config = json.loads(path.read_text(encoding="utf-8"))
    assert image_rules.MAX_IMAGE_BYTES == config["infrastructure"]["media_resolution"]["max_bytes"]


def test_allowed_mime_types_match_server_decoder():
    assert set(image_rules.ALLOWED_IMAGE_MIME_TYPES) == _server_mime_types()


def test_known_extensions_and_unknown_type():
    assert image_rules.detect_image_mime("a.JPG") == "image/jpeg"
    assert image_rules.detect_image_mime("a.png") == "image/png"
    assert image_rules.detect_image_mime("a.txt") is None
