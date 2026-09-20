import ast
from pathlib import Path

import pytest

from src.utils import image_rules

SERVER_FILE = (
    Path(__file__).resolve().parents[2]
    / "server"
    / "src"
    / "legacy"
    / "chat_input_adapter.py"
)


def _server_constants():
    if not SERVER_FILE.exists():
        pytest.skip("server tree not available for mirror check")
    tree = ast.parse(SERVER_FILE.read_text(encoding="utf-8"))
    values = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in {
                "MAX_IMAGE_BYTES",
                "ALLOWED_IMAGE_MIME_TYPES",
            }:
                values[target.id] = eval(
                    compile(ast.Expression(node.value), "<server>", "eval")
                )
    return values


def test_max_image_bytes_mirrors_server_rule():
    assert image_rules.MAX_IMAGE_BYTES == _server_constants()["MAX_IMAGE_BYTES"]


def test_allowed_mime_types_mirror_server_rule():
    server = set(_server_constants()["ALLOWED_IMAGE_MIME_TYPES"])
    assert set(image_rules.ALLOWED_IMAGE_MIME_TYPES) == server


def test_detect_image_mime_maps_known_extensions_case_insensitively():
    assert image_rules.detect_image_mime("a.JPG") == "image/jpeg"
    assert image_rules.detect_image_mime("a.jpeg") == "image/jpeg"
    assert image_rules.detect_image_mime("a.png") == "image/png"
    assert image_rules.detect_image_mime("a.gif") == "image/gif"
    assert image_rules.detect_image_mime("a.bmp") == "image/bmp"
    assert image_rules.detect_image_mime("a.webp") == "image/webp"


def test_detect_image_mime_rejects_unknown_extensions():
    assert image_rules.detect_image_mime("a.txt") is None
    assert image_rules.detect_image_mime("noext") is None
