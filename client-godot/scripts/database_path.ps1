param([switch]$Open, [string]$Root = (Join-Path $env:APPDATA 'AgentLuo-Godot'))

$history = Join-Path $Root 'history'
if (-not (Test-Path -LiteralPath $history)) {
    Write-Error "Client history directory not found: $history"
    exit 1
}

$database = Get-ChildItem -LiteralPath $history -Recurse -Filter 'history.db' -File |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if ($null -eq $database) {
    Write-Error "history.db not found under: $history"
    exit 1
}

Write-Output $database.FullName
if (Test-Path -LiteralPath ($database.FullName + '-wal')) {
    Write-Host 'WAL file exists: the app may still be running; the newest writes may not be checkpointed yet.'
}

if ($Open) {
    if (-not (Get-Command code -ErrorAction SilentlyContinue)) {
        Write-Error 'VS Code "code" command not found. Install a SQLite extension and open the path above manually.'
        exit 1
    }
    & code --file $database.FullName
}
