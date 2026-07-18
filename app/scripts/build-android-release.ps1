$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$androidRoot = Join-Path $projectRoot 'android'
$signingRoot = Join-Path $projectRoot '.android-signing'
$keyPropertiesPath = Join-Path $signingRoot 'key.properties'

# Environment variables take precedence. The ignored key.properties is a local
# convenience so a developer can run the release command without retyping values.
$localProperties = @{}
if (Test-Path -LiteralPath $keyPropertiesPath) {
    Get-Content -Encoding utf8 -LiteralPath $keyPropertiesPath | ForEach-Object {
        if ($_ -match '^\s*([^#=][^=]*)\s*=\s*(.*)$') {
            $localProperties[$matches[1].Trim()] = $matches[2].Trim()
        }
    }
}

$propertyToEnvironment = @{
    storeFile = 'MYAPP_UPLOAD_STORE_FILE'
    keyAlias = 'MYAPP_UPLOAD_KEY_ALIAS'
    storePassword = 'MYAPP_UPLOAD_STORE_PASSWORD'
    keyPassword = 'MYAPP_UPLOAD_KEY_PASSWORD'
}
foreach ($propertyName in $propertyToEnvironment.Keys) {
    $environmentName = $propertyToEnvironment[$propertyName]
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($environmentName, 'Process')) -and $localProperties.ContainsKey($propertyName)) {
        [Environment]::SetEnvironmentVariable($environmentName, $localProperties[$propertyName], 'Process')
    }
}

$requiredVariables = @(
    'MYAPP_UPLOAD_STORE_FILE',
    'MYAPP_UPLOAD_KEY_ALIAS',
    'MYAPP_UPLOAD_STORE_PASSWORD',
    'MYAPP_UPLOAD_KEY_PASSWORD'
)
$missingVariables = @(
    $requiredVariables | Where-Object {
        [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_, 'Process'))
    }
)
if ($missingVariables.Count -gt 0) {
    throw "Missing release signing environment variables: $($missingVariables -join ', ')"
}

if (-not (Test-Path -LiteralPath (Join-Path $androidRoot 'gradlew.bat'))) {
    throw 'android/ has not been generated. Run npm run prebuild:android:clean first.'
}

$androidSdk = [Environment]::GetEnvironmentVariable('ANDROID_HOME', 'Process')
if ([string]::IsNullOrWhiteSpace($androidSdk)) {
    $androidSdk = [Environment]::GetEnvironmentVariable('ANDROID_SDK_ROOT', 'Process')
}
if (-not [string]::IsNullOrWhiteSpace($androidSdk) -and -not (Test-Path -LiteralPath $androidSdk)) {
    throw "Android SDK path does not exist: $androidSdk"
}
if ([string]::IsNullOrWhiteSpace($androidSdk)) {
    throw 'Android SDK is not configured. Set ANDROID_HOME (or ANDROID_SDK_ROOT); local.properties is regenerated and may be removed by prebuild --clean.'
}
$env:ANDROID_HOME = (Resolve-Path -LiteralPath $androidSdk).Path

$storeFile = [Environment]::GetEnvironmentVariable('MYAPP_UPLOAD_STORE_FILE', 'Process')
if (-not [System.IO.Path]::IsPathRooted($storeFile)) {
    $storeFileBase = if ($localProperties.ContainsKey('storeFile')) { $signingRoot } else { $projectRoot }
    $storeFile = Join-Path $storeFileBase $storeFile
}
$resolvedStoreFile = (Resolve-Path -LiteralPath $storeFile -ErrorAction Stop).Path
$env:MYAPP_UPLOAD_STORE_FILE = $resolvedStoreFile
$env:NODE_ENV = 'production'

Push-Location $androidRoot
try {
    & .\gradlew.bat :app:assembleRelease
    if ($LASTEXITCODE -ne 0) {
        throw "Android release build failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

$releaseDirectory = Join-Path $androidRoot 'app\build\outputs\apk\release'
Write-Host "Signed release APK directory: $releaseDirectory"
