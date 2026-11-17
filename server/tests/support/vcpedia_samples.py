"""Read checked-in VCPedia examples for tests and local comparisons; no selection or certification."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

DEFAULT_MANIFEST = Path(__file__).with_name("vcpedia_corpus") / "manifest.json"


def read_manifest(path=DEFAULT_MANIFEST):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_input(root, name, expected_hash):
    path = (Path(root) / name).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError(f"Sample path is outside its directory: {name}")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError(f"Sample content changed: {name}")
    return raw


def load_samples(manifest_path=DEFAULT_MANIFEST):
    manifest_path = Path(manifest_path)
    manifest = read_manifest(manifest_path)
    pairs = {}
    for page in manifest["pages"]:
        title = page["title"]
        if title in pairs:
            raise ValueError(f"Duplicate sample title: {title}")
        source = read_input(manifest_path.parent, page["file"], page["sha256"]).decode("utf-8")
        html = None
        if page.get("capture"):
            capture = page["capture"]
            raw = read_input(manifest_path.parent, capture["path"], capture["sha256"])
            response = json.loads(gzip.decompress(raw).decode("utf-8"))
            if "body" in response:
                response = json.loads(response["body"])
            parsed = response["parse"]
            captured = parsed["wikitext"]["*"].replace("\r\n", "\n").replace("\r", "\n")
            if parsed["title"] != title or parsed["pageid"] != page["pageid"] or captured != source:
                raise ValueError(f"Mismatched wikitext and rendered input: {title}")
            html = parsed["text"]["*"]
        pairs[title] = source, html
    if not pairs:
        raise ValueError("No sample inputs")
    return manifest, pairs
