"""Build orchestration tests with a fake exporter; no engine or user data needed."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile


PROJECT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")


@unittest.skipUnless(POWERSHELL, "PowerShell required")
class BuildPromptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentluo-build-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "scripts").mkdir()
        shutil.copyfile(PROJECT / "scripts/build.ps1", self.root / "scripts/build.ps1")
        for name in ("release.json", "project.godot", "export_presets.cfg"):
            shutil.copyfile(PROJECT / name, self.root / name)
        (self.root / "licenses").mkdir()
        (self.root / "licenses/license.txt").write_text("test license")
        (self.root / "PREVIEW.md").write_text("test instructions")
        (self.root / "scripts/common.ps1").write_text('''
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
function Resolve-Godot([string]$Path) { return 'fake-engine' }
function Read-Host([string]$Prompt) {
    Write-Host $Prompt
    $answersPath = Join-Path $ProjectRoot 'answers.json'
    $answers = Get-Content $answersPath -Raw | ConvertFrom-Json
    if ($answers.Count -eq 0) { throw 'Unexpected prompt' }
    $answer = [string]$answers[0]
    ConvertTo-Json -InputObject @($answers | Select-Object -Skip 1) | Set-Content $answersPath
    return $answer
}
function Invoke-GodotChecked([string]$Executable, [string[]]$Arguments, [string]$LogName, [switch]$UseHostUserData) {
    if ($LogName -eq 'export') {
        [IO.File]::WriteAllText($Arguments[-1], 'fake exe')
        [IO.File]::WriteAllText([IO.Path]::ChangeExtension($Arguments[-1], '.pck'), 'fake pck')
    }
}
''', encoding="utf-8")

    def run_build(self, *args, answers=()):
        (self.root / "answers.json").write_text(json.dumps(answers))
        return subprocess.run(
            [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(self.root / "scripts/build.ps1"), "-Godot", "fake", *args],
            capture_output=True, timeout=30,
        )

    def metadata(self):
        return {name: (self.root / name).read_bytes() for name in
                ("release.json", "project.godot", "export_presets.cfg")}

    def assert_version(self, version, native):
        self.assertEqual(json.loads((self.root / "release.json").read_text())["version"], version)
        self.assertIn(f'config/version="{version}"', (self.root / "project.godot").read_text())
        preset = (self.root / "export_presets.cfg").read_text()
        for key in ("file_version", "product_version"):
            self.assertIn(f'application/{key}="{native}"', preset)

    def test_prompt_retry_four_parts_and_repeat_preserves_old_package(self):
        result = self.run_build(answers=["bad", "0.1.4.2"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_version("0.1.4.2", "0.1.4.2")
        original = self.root / "artifacts/agentluo-0.1.4.2.zip"
        before = original.read_bytes()
        with zipfile.ZipFile(original) as archive:
            release = json.loads(archive.read("agentluo-0.1.4.2/release.json"))
            self.assertEqual(release["version"], "0.1.4.2")
        result = self.run_build(answers=[""])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(original.read_bytes(), before)
        self.assertEqual(len(list((self.root / "artifacts").glob("*.zip"))), 2)
        self.assertEqual(len(list((self.root / "dist").iterdir())), 2)

    def test_explicit_three_parts(self):
        result = self.run_build("-Version", "0.1.5")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_version("0.1.5", "0.1.5.0")
        self.assertTrue((self.root / "artifacts/agentluo-0.1.5.zip").is_file())

    def test_invalid_versions_never_modify_metadata(self):
        before = self.metadata()
        for version in ("1.2", "1.2.3.4.5", "1.2.65536", "01.2.3", "1.2.3-beta", "../bad"):
            with self.subTest(version=version):
                result = self.run_build("-Version", version)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.metadata(), before)
        self.assertFalse((self.root / "dist").exists())

    def test_missing_native_field_never_partially_updates_metadata(self):
        (self.root / "export_presets.cfg").write_text('[preset.0]\n')
        before = self.metadata()
        result = self.run_build("-Version", "0.2.0")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.metadata(), before)


if __name__ == "__main__":
    unittest.main()
