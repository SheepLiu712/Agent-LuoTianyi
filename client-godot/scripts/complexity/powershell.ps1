param([Parameter(Mandatory = $true)][string]$Manifest)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$CallableTypes = @('FunctionDefinitionAst', 'FunctionMemberAst', 'ScriptBlockExpressionAst')

function Get-BinaryWeight($Node) {
    if ([string]$Node.Operator -in @('And', 'Or', 'AndAnd', 'OrOr')) { return 1 }
    return 0
}

function Get-NodeWeight($Node) {
    switch ($Node.GetType().Name) {
        'IfStatementAst' { return $Node.Clauses.Count }
        'SwitchStatementAst' { return $Node.Clauses.Count }
        'CatchClauseAst' { return 1 }
        'TernaryExpressionAst' { return 1 }
        'PipelineChainAst' { return (Get-BinaryWeight $Node) }
        'BinaryExpressionAst' { return (Get-BinaryWeight $Node) }
        default {
            if ($Node.GetType().Name -in @('ForStatementAst', 'ForEachStatementAst', 'WhileStatementAst', 'DoWhileStatementAst', 'DoUntilStatementAst')) { return 1 }
            return 0
        }
    }
}

function Measure-Node($Node) {
    if ($Node.GetType().Name -in $CallableTypes) { return 0 }
    $weight = Get-NodeWeight $Node
    foreach ($child in $Node.FindAll({ param($Candidate) $Candidate.Parent -eq $Node }, $false)) {
        $weight += Measure-Node $child
    }
    return $weight
}

function New-Callable($Node) {
    if ($Node.GetType().Name -eq 'ScriptBlockExpressionAst') {
        return @{ Body = $Node.ScriptBlock; Name = "<scriptblock@$($Node.Extent.StartLineNumber)>"; Kind = 'lambda'; Line = $Node.Extent.StartLineNumber }
    }
    return @{ Body = $Node.Body; Name = $Node.Name; Kind = 'function'; Line = $Node.Extent.StartLineNumber }
}

function Get-Units($Root) {
    $units = @(@{ Body = $Root; Name = '<script>'; Kind = 'script'; Line = 1 })
    foreach ($node in $Root.FindAll({ param($Candidate) $Candidate.GetType().Name -in $CallableTypes }, $true)) {
        $units += New-Callable $node
    }
    return $units
}

function Read-Script($File) {
    $tokens = $null
    $parseErrors = $null
    $root = [System.Management.Automation.Language.Parser]::ParseFile($File.full, [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count -gt 0) { throw ($parseErrors | Out-String) }
    foreach ($unit in Get-Units $root) {
        [PSCustomObject]@{
            path = $File.path; name = $unit.Name; kind = $unit.Kind
            line = $unit.Line; end_line = $unit.Body.Extent.EndLineNumber
            cc = 1 + (Measure-Node $unit.Body); decisions = @{}; language = 'PowerShell'
        }
    }
}

$records = @()
$errors = @()
foreach ($file in (Get-Content -LiteralPath $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json)) {
    try { $records += @(Read-Script $file) }
    catch { $errors += @{ path = $file.path; error = $_.Exception.Message } }
}
@{ records = @($records); errors = @($errors) } | ConvertTo-Json -Depth 8 -Compress
