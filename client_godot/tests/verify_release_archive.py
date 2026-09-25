"""Verify a release archive against the release manifest and dependency lock."""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path

LICENSE_FILES = {
    "CubismCore.md", "CubismNOTICE.md", "CubismSDK.md", "gd_cubism.adoc",
    "godot-cpp.md", "Godot-third-party.json", "Godot.txt", "RESOURCES.md",
}
DLL_FILES = {
    "libgd_cubism.windows.release.x86_64.dll": "gd_cubism",
    "windows_security.dll": "windows_security",
}


def _lock_for(source: Path) -> dict:
    candidates = [source.parent.parent / "dependencies.lock.json", source.parent / "dependencies.lock.json"]
    for candidate in candidates:
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8-sig"))
    raise AssertionError("dependency lock is required next to the project export")


def verify(archive: Path, source: Path):
    archive = archive.resolve()
    source = source.resolve()
    release_path = source / "release.json"
    assert release_path.is_file(), "release.json missing from export"
    release = json.loads(release_path.read_text(encoding="utf-8-sig"))
    assert release.get("product") == "agentluo" and isinstance(release.get("version"), str), "invalid release metadata"
    prefix = f"{release['product']}-{release['version']}/"
    assert archive.name == prefix[:-1] + ".zip", "versioned archive name"
    lock = _lock_for(source)

    expected_names = {prefix + name for name in ("agentluo.exe", "agentluo.pck", "PREVIEW.md", "release.json")}
    expected_names |= {prefix + "licenses/" + name for name in LICENSE_FILES}
    expected_names |= {prefix + name for name in DLL_FILES}
    expected = {}
    for relative in sorted(name[len(prefix):] for name in expected_names):
        path = source / Path(relative)
        assert path.is_file(), f"required release file missing: {relative}"
        expected[prefix + relative.replace("\\", "/")] = path
    source_files = {prefix + p.relative_to(source).as_posix() for p in source.rglob("*") if p.is_file()}
    assert source_files == expected_names, f"unexpected export files: {source_files.symmetric_difference(expected_names)}"

    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None, "CRC verification failed"
        infos = [info for info in z.infolist() if not info.is_dir()]
        entries = [info.filename for info in infos]
        assert len(entries) == len(set(entries)), "duplicate archive entries"
        assert set(entries) == expected_names, f"missing or extra package entries: {set(entries).symmetric_difference(expected_names)}"
        for name, path in expected.items():
            assert hashlib.sha256(z.read(name)).digest() == hashlib.sha256(path.read_bytes()).digest(), f"archive content mismatch: {name}"

    for dll_name, lock_key in DLL_FILES.items():
        digest = hashlib.sha256((source / dll_name).read_bytes()).hexdigest().lower()
        expected_digest = lock[lock_key]["binary_sha256"].lower()
        assert digest == expected_digest, f"{dll_name} SHA256 differs from dependency lock"
    result = {
        "archive": str(archive),
        "bytes": archive.stat().st_size,
        "entries": len(expected),
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "dlls": {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in DLL_FILES},
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("Release archive CRC, version, manifest and supply-chain hashes: PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    verify(args.archive, args.source)
