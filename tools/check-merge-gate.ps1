<#
.SYNOPSIS
Checks whether candidate commits can be merged from an exact target baseline.

.EXAMPLE
pwsh -File tools/check-merge-gate.ps1 dev feature/one feature/two
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateNotNullOrEmpty()]
    [string]$Target,

    [Parameter(Mandatory = $true, Position = 1, ValueFromRemainingArguments = $true)]
    [ValidateNotNullOrEmpty()]
    [string[]]$Candidate
)

Set-StrictMode -Version Latest
if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$repoRoot = Split-Path -Parent $PSScriptRoot

function Resolve-GitCommit {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Reference
    )

    $resolved = @(
        & git -C $repoRoot rev-parse --verify --quiet --end-of-options "${Reference}^{commit}" 2>$null
    )
    if ($LASTEXITCODE -ne 0 -or $resolved.Count -ne 1) {
        return $null
    }

    return $resolved[0].Trim()
}

function Format-ShortCommit {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Commit
    )

    return $Commit.Substring(0, [Math]::Min(12, $Commit.Length))
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Output "[FAIL] git is not available on PATH."
    exit 2
}

$targetCommit = Resolve-GitCommit -Reference $Target
if (-not $targetCommit) {
    Write-Output "[FAIL] Target '$Target' does not resolve to a commit."
    exit 2
}

if ($Candidate.Count -eq 0) {
    Write-Output "[FAIL] At least one candidate is required."
    exit 2
}

$targetShort = Format-ShortCommit -Commit $targetCommit
Write-Output "Merge gate target: $Target ($targetShort)"

$passed = 0
$failed = 0
$resolvedCandidates = [System.Collections.Generic.List[object]]::new()

foreach ($candidateReference in $Candidate) {
    $candidateCommit = Resolve-GitCommit -Reference $candidateReference
    if (-not $candidateCommit) {
        Write-Output "[FAIL] $candidateReference | does not resolve to a commit"
        $failed++
        continue
    }

    [void]$resolvedCandidates.Add([PSCustomObject]@{
        Reference = $candidateReference
        Commit = $candidateCommit
    })

    & git -C $repoRoot merge-base --is-ancestor $targetCommit $candidateCommit *> $null
    $ancestorExitCode = $LASTEXITCODE

    # Git for Windows 2.55 can access-violate on a conflicted merge when
    # --quiet is invoked from PowerShell. The messages/name-only form has the
    # same exit-code contract and preserves useful conflict details.
    $mergeTreeOutput = @(
        & git -C $repoRoot merge-tree --write-tree --messages --name-only $targetCommit $candidateCommit 2>&1
    )
    $mergeTreeExitCode = $LASTEXITCODE

    $reasons = [System.Collections.Generic.List[string]]::new()
    if ($ancestorExitCode -eq 1) {
        [void]$reasons.Add("target is not an ancestor")
    }
    elseif ($ancestorExitCode -ne 0) {
        [void]$reasons.Add("ancestor check failed with exit code $ancestorExitCode")
    }

    $mergeTreeDetail = ($mergeTreeOutput | ForEach-Object { $_.ToString().Trim() } | Where-Object { $_ }) -join "; "
    if ($mergeTreeExitCode -eq 1) {
        $conflictReason = "merge tree has content conflicts"
        if ($mergeTreeDetail) {
            $conflictReason += ": $mergeTreeDetail"
        }
        [void]$reasons.Add($conflictReason)
    }
    elseif ($mergeTreeExitCode -ne 0) {
        $detail = $mergeTreeDetail
        if ($detail) {
            [void]$reasons.Add("merge-tree failed with exit code ${mergeTreeExitCode}: $detail")
        }
        else {
            [void]$reasons.Add("merge-tree failed with exit code $mergeTreeExitCode")
        }
    }

    $candidateShort = Format-ShortCommit -Commit $candidateCommit
    if ($reasons.Count -eq 0) {
        Write-Output "[PASS] $candidateReference ($candidateShort) | target is an ancestor; merge tree is clean"
        $passed++
    }
    else {
        Write-Output "[FAIL] $candidateReference ($candidateShort) | $($reasons -join '; ')"
        $failed++
    }
}

$orderPassed = 0
$orderFailed = 0

for ($leftIndex = 0; $leftIndex -lt $resolvedCandidates.Count; $leftIndex++) {
    for ($rightIndex = $leftIndex + 1; $rightIndex -lt $resolvedCandidates.Count; $rightIndex++) {
        $left = $resolvedCandidates[$leftIndex]
        $right = $resolvedCandidates[$rightIndex]

        & git -C $repoRoot merge-base --is-ancestor $left.Commit $right.Commit *> $null
        $leftBeforeRight = $LASTEXITCODE
        & git -C $repoRoot merge-base --is-ancestor $right.Commit $left.Commit *> $null
        $rightBeforeLeft = $LASTEXITCODE

        if ($leftBeforeRight -eq 0 -or $rightBeforeLeft -eq 0) {
            $direction = if ($leftBeforeRight -eq 0) {
                "$($left.Reference) <= $($right.Reference)"
            }
            else {
                "$($right.Reference) <= $($left.Reference)"
            }
            Write-Output "[PASS] order | $direction"
            $orderPassed++
            continue
        }

        if ($leftBeforeRight -notin @(0, 1) -or $rightBeforeLeft -notin @(0, 1)) {
            Write-Output (
                "[FAIL] order | ancestor check failed for " +
                "$($left.Reference) and $($right.Reference)"
            )
        }
        else {
            Write-Output (
                "[FAIL] order | $($left.Reference) and $($right.Reference) " +
                "are divergent; arbitrary PR merge order is not structurally guaranteed"
            )
        }
        $orderFailed++
    }
}

$failed += $orderFailed
Write-Output (
    "Summary: $passed candidate checks passed, $orderPassed order checks passed, " +
    "$failed failed"
)

if ($failed -gt 0) {
    exit 1
}

exit 0
