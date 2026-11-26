param([string]$Godot, [string]$OutputDirectory, [switch]$Package = $true, [string]$Version)
. (Join-Path $PSScriptRoot 'common.ps1')

function Read-BuildEngine($Godot) {
    if (-not $Godot) { $Godot = $env:GODOT_BIN }
    if (-not $Godot) { $Godot = (Read-Host '请输入 Godot 4.7.1 可执行文件的完整路径').Trim().Trim('"') }
    $engine = Resolve-Godot $Godot
    return $engine
}

function Resolve-BuildDestinations($ProjectRoot, $outputRoot, $name, $Package) {
    $packagePath = Join-Path $ProjectRoot "artifacts/$name.zip"
    $destination = Join-Path $outputRoot $name
    if ((Test-Path -LiteralPath $destination) -or ($Package -and (Test-Path -LiteralPath $packagePath))) {
        $buildId = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
        $destination = Join-Path $outputRoot "$name-$buildId"
        $packagePath = Join-Path $ProjectRoot "artifacts/$name-$buildId.zip"
        Write-Host '同版本产物已存在，保留旧包，新产物名称自动添加时间戳。'
    }

    return @{packagePath=$packagePath;destination=$destination}
}

function Export-BuildFiles($temporaryDirectory, $engine, $ProjectRoot) {
    $executable = Join-Path $temporaryDirectory 'agentluo.exe'
    Invoke-GodotChecked $engine @('--headless', '--path', $ProjectRoot, '--editor', '--import') 'import'
    Invoke-GodotChecked $engine @('--headless', '--path', $ProjectRoot, '--export-release', 'Windows Desktop', $executable) 'export' -UseHostUserData
    if (-not (Test-Path -LiteralPath $executable) -or -not (Test-Path -LiteralPath (Join-Path $temporaryDirectory 'agentluo.pck'))) {
        throw 'Export did not produce agentluo.exe and agentluo.pck.'
    }
    Invoke-GodotChecked $executable @('--headless', '--quit-after', '3') 'export-startup'
    foreach ($required in @('licenses', 'PREVIEW.md', 'release.json')) {
        $source = Join-Path $ProjectRoot $required
        if (-not (Test-Path -LiteralPath $source)) { throw "Missing release input: $required" }
        Copy-Item -LiteralPath $source -Destination $temporaryDirectory -Recurse -Force
    }
}

function Read-BuildVersion($Version, $release, $interactiveVersion) {
    do {
        if ($interactiveVersion) {
            $Version = Read-Host "请输入版本号（回车沿用 $($release.version)，例如 0.1.5 或 0.1.4.2）"
            if ([string]::IsNullOrWhiteSpace($Version)) { $Version = [string]$release.version }
        }
        $Version = $Version.Trim()
        $validVersion = $Version -cmatch '^(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})(\.(0|[1-9][0-9]{0,4}))?$'
        if ($validVersion) {
            $validVersion = @($Version.Split('.') | Where-Object { [int]$_ -gt 65535 }).Count -eq 0
        }
        if (-not $validVersion) {
            if (-not $interactiveVersion) { throw '版本号须为三段或四段数字，每段 0..65535，不带前导零。' }
            Write-Host '版本号须为三段或四段数字，每段 0..65535，不带前导零，请重新输入。'
        }
    } until ($validVersion)

    return $Version
}

function Update-ReleaseVersions($Version, $releasePath, $ProjectRoot) {
    $nativeVersion = $Version
    if ($Version.Split('.').Count -eq 3) { $nativeVersion += '.0' }
    $updates = @(
        @{ Path = $releasePath; Pattern = '("version"\s*:\s*")[^"]*(")'; Value = $Version; Count = 1 },
        @{ Path = (Join-Path $ProjectRoot 'project.godot'); Pattern = '(?m)^(config/version=")[^"]*(")'; Value = $Version; Count = 1 },
        @{ Path = (Join-Path $ProjectRoot 'export_presets.cfg'); Pattern = '(?m)^(application/(?:file_version|product_version)=")[^"]*(")'; Value = $nativeVersion; Count = 2 }
    )
    Prepare-VersionUpdates $updates
    try {
        foreach ($update in $updates) {
            if ($update.NeedsWrite) {
                $update.Changed = $true
                [IO.File]::WriteAllText($update.Path, $update.Content, (New-Object Text.UTF8Encoding($false)))
            }
        }
    } catch {
        foreach ($update in $updates) {
            if ($update.Changed) { [IO.File]::WriteAllBytes($update.Path, $update.Original) }
        }
        throw
    }

    return $nativeVersion
}

function Prepare-VersionUpdates($updates) {
    foreach ($update in $updates) {
        $original = [IO.File]::ReadAllText($update.Path)
        if ([regex]::Matches($original, $update.Pattern).Count -ne $update.Count) {
            throw "Missing or ambiguous version fields: $($update.Path)"
        }
        $update.Original = [IO.File]::ReadAllBytes($update.Path)
        $update.Changed = $false
        $update.Content = [regex]::Replace($original, $update.Pattern, ('${1}' + $update.Value + '${2}'))
        $update.NeedsWrite = $update.Content -cne $original
    }
}

function Write-VerifiedArchive($temporaryDirectory, $temporaryZip, $name) {
    $files = @(Get-ChildItem -LiteralPath $temporaryDirectory -File -Recurse)
    $archive = [IO.Compression.ZipFile]::Open($temporaryZip, [IO.Compression.ZipArchiveMode]::Create)
    try {
        foreach ($file in $files) {
            $relative = $file.FullName.Substring($temporaryDirectory.Length + 1).Replace('\', '/')
            [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $file.FullName, "$name/$relative", [IO.Compression.CompressionLevel]::Optimal) | Out-Null
        }
    } finally { $archive.Dispose() }
    Test-BuildArchive $temporaryZip $temporaryDirectory $name $files
}

function Test-BuildArchive($temporaryZip, $temporaryDirectory, $name, $files) {
    $archive = [IO.Compression.ZipFile]::OpenRead($temporaryZip)
    try {
        $entries = @($archive.Entries | Where-Object { $_.Name })
        if ($entries.Count -ne $files.Count) { throw 'Archive file count mismatch.' }
        foreach ($file in $files) {
            $relative = $file.FullName.Substring($temporaryDirectory.Length + 1).Replace('\', '/')
            $entry = $archive.GetEntry("$name/$relative")
            if (-not $entry -or $entry.Length -ne $file.Length) { throw "Missing or truncated archive entry: $relative" }
        }
    } finally { $archive.Dispose() }
}

$releasePath = Join-Path $ProjectRoot 'release.json'
$release = Get-Content -LiteralPath $releasePath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($release.product -cne 'agentluo') { throw 'Invalid release product.' }
$Version = Read-BuildVersion $Version $release (-not $PSBoundParameters.ContainsKey('Version'))

$engine = Read-BuildEngine $Godot
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $ProjectRoot 'dist' }
$outputRoot = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
$name = "agentluo-$Version"
$paths = Resolve-BuildDestinations $ProjectRoot $outputRoot $name $Package
$packagePath = $paths.packagePath
$destination = $paths.destination

# Validate all fields before writing; preserve unrelated project options.
$nativeVersion = Update-ReleaseVersions $Version $releasePath $ProjectRoot
Write-Host "正在打包 $Version（EXE 版本 $nativeVersion）"

# Export into a fresh sibling directory. A failed or interrupted export can
# therefore never leave stale files that are accidentally published later.
$temporaryDirectory = Join-Path $outputRoot ("." + $name + "." + [Guid]::NewGuid().ToString('N') + ".building")
New-Item -ItemType Directory -Force -Path $temporaryDirectory | Out-Null
$temporaryZip = $null
try {
    Export-BuildFiles $temporaryDirectory $engine $ProjectRoot
    if ($Package) {
        Add-Type -AssemblyName System.IO.Compression
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $temporaryZip = Join-Path $ProjectRoot ("artifacts/" + $name + "." + [Guid]::NewGuid().ToString('N') + ".building.zip")
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $temporaryZip) | Out-Null
        Write-VerifiedArchive $temporaryDirectory $temporaryZip $name

    }
    # Directory.Move is atomic on one volume and refuses to overwrite an
    # existing destination, so publication happens only after all checks pass.
    [IO.Directory]::Move($temporaryDirectory, $destination)
    $temporaryDirectory = $null
    if ($temporaryZip) {
        [IO.File]::Move($temporaryZip, $packagePath)
        $temporaryZip = $null
        Write-Host "Package: $packagePath"
    }
} finally {
    if ($temporaryDirectory -and (Test-Path -LiteralPath $temporaryDirectory)) { Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force -ErrorAction SilentlyContinue }
    if ($temporaryZip -and (Test-Path -LiteralPath $temporaryZip)) { Remove-Item -LiteralPath $temporaryZip -Force -ErrorAction SilentlyContinue }
}
Write-Host "Build: $(Join-Path $destination 'agentluo.exe')"
