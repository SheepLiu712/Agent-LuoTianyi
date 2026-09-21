param([string]$Godot, [Parameter(Mandatory=$true)][string]$Python)
. (Join-Path $PSScriptRoot 'common.ps1')
$engine = Resolve-Godot $Godot
$groups = @{
    'run_history_tests.py' = @('test_history_sync.gd', 'test_history_media.gd', 'ui/test_image_sending.gd')
    'run_feature_tests.py' = @('application/test_extension_contracts.gd', 'test_preferences.gd', 'ui/test_unified_settings.gd', 'ui/test_model_cards.gd', 'ui/test_settings_control_states.gd', 'ui/test_logout_confirmation.gd', 'test_application_drafts.gd', 'test_model_settings.gd', 'test_model_execution.gd')
    'run_dynamics_tests.py' = @('test_dynamics.gd', 'test_dynamics_detail.gd', 'ui/test_comment_feedback.gd')
}
foreach ($runner in $groups.Keys) {
    foreach ($test in $groups[$runner]) {
        & $Python (Join-Path $ProjectRoot "tests/$runner") --godot $engine --script "res://tests/$test"
        if ($LASTEXITCODE -ne 0) { throw "$test failed." }
    }
}
