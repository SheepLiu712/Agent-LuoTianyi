"""Build the Windows-only credential extension against the locked godot-cpp."""
import argparse
import codecs
import encodings.oem
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--godot-cpp", type=Path, required=True)
args = parser.parse_args()
project = Path(__file__).resolve().parents[1]
lock = json.loads((project / "dependencies.lock.json").read_text(encoding="utf-8-sig"))
native_status = subprocess.check_output(
    ["git", "-C", str(project), "status", "--porcelain", "--untracked-files=all", "--",
     "native", "addons/windows_security"], text=True)
if native_status.strip():
    raise RuntimeError("Refusing to build WindowsSecurity from a dirty native source tree")
cpp = args.godot_cpp.absolute()
if not cpp.is_dir():
    raise RuntimeError(f"godot-cpp source directory does not exist: {cpp}")
status = subprocess.check_output(["git", "-C", str(cpp), "status", "--porcelain", "--untracked-files=all"], text=True)
if status.strip():
    raise RuntimeError("Refusing to build dirty godot-cpp checkout")
revision = subprocess.check_output(["git", "-C", str(cpp), "rev-parse", "HEAD"], text=True).strip()
if revision != lock["gd_cubism"]["godot_cpp_commit"]:
    raise RuntimeError("godot-cpp revision differs from dependency lock")
import SCons
if SCons.__version__ != lock["native_build"]["scons"]:
    raise RuntimeError("SCons version differs from dependency lock")
print(f"Build toolchain: python={sys.version.split()[0]} scons={SCons.__version__} godot_cpp={revision}")
encodings.oem.oem_decode = lambda data, errors="strict", final=False: (bytes(data).decode("utf-8", errors), len(data))
os.chdir(project / "native")
sys.argv = ["scons", "platform=windows", "arch=x86_64", "target=template_release", f"godot_cpp={cpp}", "-j8"]
from SCons.Script import main
try:
    main()
except SystemExit as result:
    if result.code not in (0, None):
        raise
binary = project / "addons/windows_security/bin/windows_security.dll"
if not binary.is_file():
    raise RuntimeError(f"Native build did not produce {binary}")
with binary.open("rb") as stream:
    digest = hashlib.file_digest(stream, "sha256").hexdigest()
expected = lock["windows_security"]["binary_sha256"].lower()
if digest.lower() != expected:
    raise RuntimeError(f"WindowsSecurity SHA256 differs from dependency lock: {digest}")
print("WindowsSecurity SHA256:", digest)
