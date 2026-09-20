param([string]$Godot, [Parameter(Mandatory=$true)][string]$Python)
. (Join-Path $PSScriptRoot 'common.ps1')
$engine = Resolve-Godot $Godot
Invoke-GodotChecked $engine @('--headless', '--path', $ProjectRoot, '--script', 'res://tests/test_reliable_outbox.gd') 'reliable-outbox'
& $Python (Join-Path $ProjectRoot 'tests/run_websocket_tests.py') --godot $engine
if ($LASTEXITCODE -ne 0) { throw 'WebSocket tests failed.' }
& $Python (Join-Path $ProjectRoot 'tests/run_websocket_tests.py') --godot $engine --script res://tests/test_live_chat.gd
if ($LASTEXITCODE -ne 0) { throw 'Live chat tests failed.' }
& $Python (Join-Path $ProjectRoot 'tests/run_websocket_tests.py') --godot $engine --script res://tests/test_voice_chat.gd
if ($LASTEXITCODE -ne 0) { throw 'Voice chat tests failed.' }
& $Python (Join-Path $ProjectRoot 'tests/run_websocket_tests.py') --godot $engine --script res://tests/avatar/test_touch_delivery.gd
if ($LASTEXITCODE -ne 0) { throw 'Avatar touch delivery tests failed.' }
