"""Build the locked upstream plugin; no source patches or global codec changes."""
import argparse
import codecs
import encodings.oem
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--console-encoding", default="utf-8", choices=["utf-8", "gbk"])
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    lock = json.loads((project / "dependencies.lock.json").read_text(encoding="utf-8-sig"))
    source = args.source.resolve()
    if not source.is_dir() or not (source / "godot-cpp").is_dir():
        raise RuntimeError(f"Cubism source or bundled godot-cpp is missing: {source}")
    for directory, expected in [(source, lock["gd_cubism"]["commit"]),
                                (source / "godot-cpp", lock["gd_cubism"]["godot_cpp_commit"])]:
        status = subprocess.check_output(["git", "-C", str(directory), "status", "--porcelain", "--untracked-files=all"], text=True)
        if status.strip():
            raise RuntimeError(f"Refusing to build dirty checkout: {directory}")
        actual = subprocess.check_output(["git", "-C", str(directory), "rev-parse", "HEAD"], text=True).strip()
        if actual != expected:
            raise RuntimeError(f"Unexpected source revision in {directory}: {actual}")
    import SCons
    if SCons.__version__ != lock["native_build"]["scons"]:
        raise RuntimeError("Use SCons " + lock["native_build"]["scons"])
    print(f"Build toolchain: python={sys.version.split()[0]} scons={SCons.__version__} cubism={lock['gd_cubism']['commit']} godot_cpp={lock['gd_cubism']['godot_cpp_commit']}")
    # Some Windows runner sessions cannot resolve the OEM pseudo-codepage.
    # Scope the workaround to this build process. The command host's encoding
    # can differ from GetOEMCP (936 on this machine, UTF-8 in its cmd output).
    codec = args.console_encoding
    codecs.lookup(codec)
    encodings.oem.oem_decode = lambda data, errors="strict", final=False: (
        bytes(data).decode(codec, errors), len(data))
    os.chdir(source)
    sys.argv = ["scons", "platform=windows", "arch=x86_64", "target=template_release", f"-j{args.jobs}"]
    from SCons.Script import main as scons_main
    try:
        scons_main()
    except SystemExit as result:
        if result.code not in (0, None):
            raise
    binary = source / "demo/addons/gd_cubism/bin/libgd_cubism.windows.release.x86_64.dll"
    if not binary.is_file():
        raise RuntimeError(f"Cubism build did not produce {binary}")
    destination = project / "addons/gd_cubism/bin" / binary.name
    shutil.copy2(binary, destination)
    with destination.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    expected = lock["gd_cubism"]["binary_sha256"].lower()
    if digest.lower() != expected:
        raise RuntimeError(f"Cubism SHA256 differs from dependency lock: {digest}")
    print("Built SHA-256:", digest)


if __name__ == "__main__":
    main()
