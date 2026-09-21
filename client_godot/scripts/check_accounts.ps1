param([string]$Godot, [Parameter(Mandatory=$true)][string]$Python)
. (Join-Path $PSScriptRoot 'common.ps1')
$engine = Resolve-Godot $Godot
& $Python (Join-Path $ProjectRoot 'tests/run_security_interop.py') --godot $engine
if ($LASTEXITCODE -ne 0) { throw 'Native interoperability failed.' }
foreach ($script in @('test_account_api.gd', 'test_account_session.gd', 'session/test_login_profiles.gd', 'test_account_view.gd', 'test_application_window.gd')) {
    & $Python (Join-Path $ProjectRoot 'tests/run_account_tests.py') --godot $engine --script "res://tests/$script"
    if ($LASTEXITCODE -ne 0) { throw "Account check failed: $script" }
}
