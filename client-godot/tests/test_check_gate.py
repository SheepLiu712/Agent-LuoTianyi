"""Exercise the official gate without an engine or installed analysis packages."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")


@unittest.skipUnless(POWERSHELL, "PowerShell required")
class CheckGateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="agentluo-check-gate-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        scripts = self.root / "scripts"
        scripts.mkdir()
        shutil.copyfile(PROJECT / "scripts/check.ps1", scripts / "check.ps1")
        (scripts / "common.ps1").write_text("""
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
function Resolve-Godot([string]$Path) { return 'fake-engine' }
function Invoke-GodotChecked([string]$Executable, [string[]]$Arguments, [string]$LogName, [switch]$RequirePass) {
    Add-Content (Join-Path $ProjectRoot 'engine-calls.txt') $LogName
}
""", encoding="utf-8")
        self.checker = scripts / "check_complexity.py"
        self.checker.write_text("""
import os
from pathlib import Path
import sys
Path(__file__).resolve().parents[1].joinpath('gate-called.txt').write_text('yes')
print('Complexity fixture invoked')
sys.exit(int(os.environ.get('TEST_GATE_EXIT', '0')))
""", encoding="utf-8")

    def run_gate(self, *flags, exit_code=0, explicit_python=True):
        arguments = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                     str(self.root / "scripts/check.ps1"), "-Godot", "fake", *flags]
        if explicit_python:
            arguments.extend(["-Python", sys.executable])
        return subprocess.run(arguments, env={**os.environ, "TEST_GATE_EXIT": str(exit_code)},
                              capture_output=True, timeout=30)

    def engine_calls(self):
        path = self.root / "engine-calls.txt"
        return path.read_text().splitlines() if path.exists() else []

    def test_success_runs_gate_and_remaining_checks(self):
        result = self.run_gate("-SkipImport")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.root / "gate-called.txt").exists())
        self.assertIn("image-attachment", self.engine_calls())
        self.assertEqual(self.engine_calls()[-1], "platform-degradation")

    def test_nonzero_gate_prevents_behavior_checks(self):
        result = self.run_gate("-SkipImport", exit_code=1)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.engine_calls(), [])

    def test_missing_dependency_is_not_silently_skipped(self):
        self.checker.write_text("import nonexistent_godot_gate_dependency\n", encoding="utf-8")
        result = self.run_gate("-SkipImport")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.engine_calls(), [])
        self.assertIn(b"nonexistent_godot_gate_dependency", result.stderr)

    def test_import_only_does_not_require_python(self):
        result = self.run_gate("-ImportOnly", exit_code=1)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.engine_calls(), ["import"])
        self.assertFalse((self.root / "gate-called.txt").exists())

    def test_skip_import_still_enforces_gate(self):
        result = self.run_gate("-SkipImport", exit_code=2)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.root / "gate-called.txt").exists())

    def test_default_python_is_compatible(self):
        result = self.run_gate("-SkipImport", explicit_python=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
