#requires -Version 5.1
<#
.SYNOPSIS
    Copy this server's runtime files and data to E:\server.
.DESCRIPTION
    This is a one-time, non-destructive migration. It copies Python source,
    configuration, runtime resources, persistent data and installation files.
    Stop server_main.py before running it so SQLite databases and their WAL
    files are copied from a consistent state. It never mirrors or deletes
    files in the destination.
.EXAMPLE
    .\scripts\deploy_to_e_server.ps1 -PlanOnly
.EXAMPLE
    .\scripts\deploy_to_e_server.ps1
.EXAMPLE
    .\scripts\deploy_to_e_server.ps1 -Resume
#>
[CmdletBinding()]
param(
    [string]$SourceRoot = (Join-Path $PSScriptRoot '..'),
    [string]$DestinationRoot = 'E:\server',
    [switch]$PlanOnly,
    [switch]$Resume
)

$ErrorActionPreference = 'Stop'

function Copy-RuntimeTree {
    param(
        [string]$RelativePath,
        [string[]]$ExcludedDirectories,
        [string[]]$ExcludedFiles
    )

    $sourcePath = Join-Path $source $RelativePath
    $destinationPath = Join-Path $destination $RelativePath
    $robocopyArgs = @(
        $sourcePath, $destinationPath, '/E', '/COPY:DAT', '/DCOPY:DAT',
        '/R:2', '/W:1', '/XJ', '/NP', '/NFL', '/NDL', '/XD'
    ) + $ExcludedDirectories + @('/XF') + $ExcludedFiles
    if ($PlanOnly) {
        $robocopyArgs += '/L'
    }

    Write-Host "Copying $RelativePath ..."
    & robocopy @robocopyArgs
    $robocopyResult = $LASTEXITCODE
    if ($robocopyResult -ge 8) {
        throw "robocopy failed for $RelativePath (exit code $robocopyResult)."
    }
}

$source = (Resolve-Path -LiteralPath $SourceRoot).Path.TrimEnd('\', '/')
$destinationFull = [System.IO.Path]::GetFullPath($DestinationRoot)
$destination = $destinationFull.TrimEnd('\', '/')
$comparison = [System.StringComparison]::OrdinalIgnoreCase
$sourcePrefix = $source + [System.IO.Path]::DirectorySeparatorChar
$destinationPrefix = $destination + [System.IO.Path]::DirectorySeparatorChar

if ($destination.Equals(([System.IO.Path]::GetPathRoot($destinationFull)).TrimEnd('\', '/'), $comparison) -or
    $destination.Equals($source, $comparison) -or
    $destination.StartsWith($sourcePrefix, $comparison) -or
    $source.StartsWith($destinationPrefix, $comparison)) {
    throw 'Source and destination must be separate directories; the destination cannot be a drive root.'
}

$requiredPaths = @(
    'server_main.py', 'pyproject.toml', 'README.md', 'setup.bat',
    'scripts/install_windows.bat', 'src', 'config/config.json',
    'res/admin_ui/admin_static/index.html', 'data'
)
foreach ($relativePath in $requiredPaths) {
    if (-not (Test-Path -LiteralPath (Join-Path $source $relativePath))) {
        throw "Required runtime path is missing: $relativePath"
    }
}

if (-not (Get-Command robocopy -ErrorAction SilentlyContinue)) {
    throw 'robocopy is required on Windows.'
}
if ((Test-Path -LiteralPath $destination) -and
    -not (Test-Path -LiteralPath $destination -PathType Container)) {
    throw "Destination is not a directory: $destination"
}
if ((Test-Path -LiteralPath $destination) -and -not $Resume -and -not $PlanOnly) {
    $existingItem = Get-ChildItem -LiteralPath $destination -Force | Select-Object -First 1
    if ($null -ne $existingItem) {
        throw "Destination is not empty: $destination. Use -Resume to copy without deleting existing files."
    }
}

if (-not $PlanOnly) {
    # A live SQLite/Chroma store cannot be safely migrated with a file copy.
    $runningServers = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" |
        Where-Object { $_.CommandLine -match 'server_main\.py' })
    if ($runningServers.Count -gt 0) {
        $processIds = ($runningServers | ForEach-Object { $_.ProcessId }) -join ', '
        throw "Stop server_main.py before migrating data. Running PID(s): $processIds"
    }
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
}

$commonExcludedDirectories = @(
    '__pycache__', '.pytest_cache', '.ruff_cache', '.mypy_cache', '.hypothesis',
    '.venv', 'venv', 'env', 'node_modules', '.git', '.vscode', '.idea'
)
$excludedDirectories = $commonExcludedDirectories + @(
    (Join-Path $source 'res/admin_ui'),
    (Join-Path $source 'config/backups'),
    (Join-Path $source 'data/test_outputs')
)
$excludedFiles = @(
    '*.pyc', '*.pyo', '*.log', '*.log.*', '.coverage*', 'Thumbs.db', '.DS_Store',
    '*.tsbuildinfo', (Join-Path $source 'config/qq_login_qr.png')
)

foreach ($relativePath in @('src', 'config', 'res', 'data')) {
    Copy-RuntimeTree -RelativePath $relativePath -ExcludedDirectories $excludedDirectories -ExcludedFiles $excludedFiles
}
Copy-RuntimeTree -RelativePath 'res/admin_ui/admin_static' -ExcludedDirectories $commonExcludedDirectories -ExcludedFiles $excludedFiles

foreach ($relativePath in @('server_main.py', 'pyproject.toml', 'README.md', 'setup.bat', 'scripts/install_windows.bat')) {
    Write-Host "Copying $relativePath ..."
    if (-not $PlanOnly) {
        $targetFile = Join-Path $destination $relativePath
        New-Item -ItemType Directory -Path (Split-Path -Parent $targetFile) -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $source $relativePath) -Destination $targetFile -Force
    }
}

if ($PlanOnly) {
    Write-Host "Plan complete. No files were copied to $destination."
} else {
    Write-Host "Migration complete: $destination"
    Write-Host 'Python/Conda packages, FFmpeg, Playwright Chromium and environment variables are not copied; install/configure them separately.'
}
$global:LASTEXITCODE = 0
