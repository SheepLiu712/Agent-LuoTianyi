import ast
import json
from pathlib import Path

import pytest

from src.utils import image_rules

SERVER_ROOT = Path(__file__).resolve().parents[2] / "server"


def _server_mime_types():
    source = SERVER_ROOT / "src" / "infrastructure" / "media" / "image_validation.py"
    if not source.exists():
        pytest.skip("server tree not available for mirror check")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    mapping = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_FORMAT_MIME" for target in node.targets)
    )
    return set(mapping.values()) | {"image/jpg"}


def test_max_image_bytes_mirrors_server_rule():
    config_path = SERVER_ROOT / "config" / "config.json"
    if not config_path.exists():
        pytest.skip("server tree not available for mirror check")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert image_rules.MAX_IMAGE_BYTES == config["infrastructure"]["media_resolution"]["max_bytes"]


def test_allowed_mime_types_mirror_server_rule():
    assert set(image_rules.ALLOWED_IMAGE_MIME_TYPES) == _server_mime_types()


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
