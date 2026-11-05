import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def analyze_files(paths, root):
    executable = shutil.which("pwsh") or shutil.which("powershell")
    if not executable:
        raise RuntimeError("PowerShell is required to parse the project's PowerShell scripts")
    helper = Path(__file__).with_suffix(".ps1")
    manifest = [{"full": str(path), "path": path.relative_to(root).as_posix()} for path in paths]
    with tempfile.TemporaryDirectory(prefix="agentluo-complexity-") as directory:
        destination = Path(directory) / "paths.json"
        destination.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run(
            [executable, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(helper), "-Manifest", str(destination)],
            capture_output=True, check=True, timeout=120,
        )
    return json.loads(result.stdout.decode("utf-8-sig"))
