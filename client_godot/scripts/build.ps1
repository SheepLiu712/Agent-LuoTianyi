param([string]$Godot, [string]$OutputDirectory, [switch]$Package)
. (Join-Path $PSScriptRoot 'common.ps1')

$engine = Resolve-Godot $Godot
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $ProjectRoot 'dist' }
$outputRoot = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
$release = Get-Content -LiteralPath (Join-Path $ProjectRoot 'release.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($release.product -cne 'agentluo' -or $release.version -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid release metadata.' }
$name = "agentluo-$($release.version)"
$packagePath = Join-Path $ProjectRoot "artifacts/$name.zip"
$destination = Join-Path $outputRoot $name
if (Test-Path -LiteralPath $destination) { throw "Delivery already exists: $destination" }
if ($Package -and (Test-Path -LiteralPath $packagePath)) { throw "Delivery already exists: $packagePath" }

# Export into a fresh sibling directory. A failed or interrupted export can
# therefore never leave stale files that are accidentally published later.
$temporaryDirectory = Join-Path $outputRoot ("." + $name + "." + [Guid]::NewGuid().ToString('N') + ".building")
New-Item -ItemType Directory -Force -Path $temporaryDirectory | Out-Null
$temporaryZip = $null
try {
    $executable = Join-Path $temporaryDirectory 'agentluo.exe'
    Invoke-GodotChecked $engine @('--headless', '--path', $ProjectRoot, '--editor', '--import') 'import'
    Invoke-GodotChecked $engine @('--headless', '--path', $ProjectRoot, '--export-release', 'Windows Desktop', $executable) 'export'
    if (-not (Test-Path -LiteralPath $executable) -or -not (Test-Path -LiteralPath (Join-Path $temporaryDirectory 'agentluo.pck'))) {
        throw 'Export did not produce agentluo.exe and agentluo.pck.'
    }
    Invoke-GodotChecked $executable @('--headless', '--quit-after', '3') 'export-startup'
    foreach ($required in @('licenses', 'PREVIEW.md', 'release.json')) {
        $source = Join-Path $ProjectRoot $required
        if (-not (Test-Path -LiteralPath $source)) { throw "Missing release input: $required" }
        Copy-Item -LiteralPath $source -Destination $temporaryDirectory -Recurse -Force
    }
    if ($Package) {
        Add-Type -AssemblyName System.IO.Compression
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $temporaryZip = Join-Path $ProjectRoot ("artifacts/" + $name + "." + [Guid]::NewGuid().ToString('N') + ".building.zip")
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $temporaryZip) | Out-Null
        $files = @(Get-ChildItem -LiteralPath $temporaryDirectory -File -Recurse)
        $archive = [IO.Compression.ZipFile]::Open($temporaryZip, [IO.Compression.ZipArchiveMode]::Create)
        try {
            foreach ($file in $files) {
                $relative = $file.FullName.Substring($temporaryDirectory.Length + 1).Replace('\', '/')
                [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $file.FullName, "$name/$relative", [IO.Compression.CompressionLevel]::Optimal) | Out-Null
            }
        } finally { $archive.Dispose() }
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
