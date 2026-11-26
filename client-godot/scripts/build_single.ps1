param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Godot,
    [string]$BuildDirectory,
    [string]$OutputDirectory,
    [switch]$Build,
    [switch]$SkipRunCheck
)

. (Join-Path $PSScriptRoot 'common.ps1')

function Assert-Version([string]$value) {
    $valid = $value -cmatch '^(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})(\.(0|[1-9][0-9]{0,4}))?$'
    if (-not $valid) { throw '版本号须为三段或四段数字，每段 0..65535，不带前导零。' }
    if (@($value.Split('.') | Where-Object { [int]$_ -gt 65535 }).Count -gt 0) {
        throw '版本号每段必须在 0..65535 之间。'
    }
}

function Find-BuildDirectory([string]$version) {
    $exact = Join-Path $ProjectRoot "dist/agentluo-$version"
    if (Test-Path -LiteralPath $exact -PathType Container) { return $exact }
    $candidates = @(Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'dist') -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "agentluo-$version-*" } |
        Sort-Object LastWriteTime -Descending)
    if ($candidates.Count -eq 0) {
        throw "找不到 dist/agentluo-$version，请先运行 build.ps1 或传入 -BuildDirectory。"
    }
    return $candidates[0].FullName
}

function Get-VersionFields([string]$version) {
    if ($version.Split('.').Count -eq 3) {
        return @{ assembly = $version; file = "$version.0"; product = $version }
    }
    return @{ assembly = $version; file = $version; product = $version }
}

function Write-LauncherSource([string]$target, [string]$version, [string]$launcherVersion) {
    $template = Join-Path $PSScriptRoot 'single-launcher/Launcher.cs'
    if (-not (Test-Path -LiteralPath $template -PathType Leaf)) { throw "缺少启动器模板：$template" }
    $fields = Get-VersionFields $version
    $text = [IO.File]::ReadAllText($template)
    $text = $text.Replace('__ASSEMBLY_VERSION__', $fields.assembly)
    $text = $text.Replace('__FILE_VERSION__', $fields.file)
    $text = $text.Replace('__PRODUCT_VERSION__', $fields.product)
    $text = $text.Replace('__LAUNCHER_VERSION__', $launcherVersion)
    [IO.File]::WriteAllText($target, $text, (New-Object Text.UTF8Encoding($false)))
}

function Get-BuildRoot([bool]$Build, [string]$Godot, [string]$Version, [string]$BuildDirectory) {
    if ($Build) {
        $buildArgs = @('-Version', $Version)
        if ($Godot) { $buildArgs += @('-Godot', $Godot) }
        & (Join-Path $PSScriptRoot 'build.ps1') @buildArgs
        if (-not $?) { throw 'build.ps1 failed.' }
        $latest = @(Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'dist') -Directory |
            Where-Object { $_.Name -like "agentluo-$Version*" } |
            Sort-Object LastWriteTime -Descending)
        if ($latest.Count -eq 0) { throw "构建后仍找不到 dist/agentluo-$Version。" }
        return $latest[0].FullName
    }
    if ($BuildDirectory) { return [IO.Path]::GetFullPath($BuildDirectory) }
    return Find-BuildDirectory $Version
}

function Test-BuildFiles([string]$buildRoot, [string]$Version) {
    foreach ($required in @('agentluo.exe', 'agentluo.pck', 'release.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path $buildRoot $required) -PathType Leaf)) {
            throw "构建目录缺少 $required：$buildRoot"
        }
    }
    $release = Get-Content -LiteralPath (Join-Path $buildRoot 'release.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$release.version -cne $Version) {
        throw "构建目录版本 $($release.version) 与 -Version $Version 不一致。"
    }
}

function Resolve-Tools {
    $icon = Join-Path $ProjectRoot 'assets/ui/app_icon.ico'
    if (-not (Test-Path -LiteralPath $icon -PathType Leaf)) { throw "缺少应用图标：$icon" }
    $csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
    if (-not (Test-Path -LiteralPath $csc -PathType Leaf)) { throw "找不到 .NET Framework csc.exe：$csc" }
    return @{ icon = $icon; csc = $csc }
}

function New-SingleExecutable([string]$buildRoot, [string]$Version, [string]$icon, [string]$csc) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $work = Join-Path (Join-Path $ProjectRoot 'tmp') "single-launcher-build-$stamp"
    $payload = Join-Path $work 'payload.zip'
    $source = Join-Path $work 'Launcher.cs'
    $single = Join-Path $work "agentluo-$Version-single.exe"
    try {
        New-Item -ItemType Directory -Force -Path $work | Out-Null
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [IO.Compression.ZipFile]::CreateFromDirectory($buildRoot, $payload, [IO.Compression.CompressionLevel]::Optimal, $false)
        Write-LauncherSource $source $Version "$Version-$stamp"
        & $csc /nologo /codepage:65001 /target:winexe /win32icon:$icon /out:$single /resource:$payload,payload.zip `
            /r:System.Windows.Forms.dll /r:System.IO.Compression.dll /r:System.IO.Compression.FileSystem.dll $source
        if ($LASTEXITCODE -ne 0) { throw "csc failed: $LASTEXITCODE" }
        return @{ path = $single; work = $work }
    }
    catch {
        Remove-LauncherWork $work
        throw
    }
}

function Copy-SingleExecutable([string]$single, [string]$Version, [string]$OutputDirectory) {
    if (-not $OutputDirectory) { $OutputDirectory = [Environment]::GetFolderPath('Desktop') }
    $outputRoot = [IO.Path]::GetFullPath($OutputDirectory)
    New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
    $destination = Join-Path $outputRoot "agentluo-$Version-single.exe"
    Copy-Item -LiteralPath $single -Destination $destination -Force
    return $destination
}

function Write-SingleReport([string]$destination) {
    $info = (Get-Item -LiteralPath $destination).VersionInfo
    Write-Host "Single: $destination"
    Write-Host "Size: $((Get-Item -LiteralPath $destination).Length) bytes"
    Write-Host "FileVersion: $($info.FileVersion) ProductVersion: $($info.ProductVersion)"
    Write-Host "SHA256: $((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant())"
}

function Test-SingleStartup([string]$destination) {
    & $destination --launcher-wait --headless --quit-after 3
    if ($LASTEXITCODE -ne 0) { throw "single exe startup failed: $LASTEXITCODE" }
    Write-Host 'Single exe startup passed.'
}

function Remove-LauncherWork([string]$work) {
    if (-not $work -or -not (Test-Path -LiteralPath $work)) { return }
    $fullWork = [IO.Path]::GetFullPath($work)
    $allowed = [IO.Path]::GetFullPath((Join-Path $ProjectRoot 'tmp'))
    if ($fullWork.StartsWith($allowed + '\', [StringComparison]::OrdinalIgnoreCase)) {
        [IO.Directory]::Delete($fullWork, $true)
    }
}

Assert-Version $Version
$buildRoot = Get-BuildRoot ([bool]$Build) $Godot $Version $BuildDirectory
Test-BuildFiles $buildRoot $Version
$tools = Resolve-Tools
$work = $null
try {
    $built = New-SingleExecutable $buildRoot $Version $tools.icon $tools.csc
    $work = $built.work
    $destination = Copy-SingleExecutable $built.path $Version $OutputDirectory
    Write-SingleReport $destination
    if (-not $SkipRunCheck) { Test-SingleStartup $destination }
}
finally {
    Remove-LauncherWork $work
}
