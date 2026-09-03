param(
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 30)]
    [int]$Day,

    [Parameter(Mandatory = $true)]
    [string]$Title
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$template = Join-Path $repoRoot 'docs\progress\DAY_REPORT_TEMPLATE.md'
$dayNumber = '{0:D2}' -f $Day
$destination = Join-Path $repoRoot "docs\progress\day-$dayNumber.md"

if (Test-Path -LiteralPath $destination) {
    throw "Daily report already exists: $destination"
}

$content = Get-Content -LiteralPath $template -Raw -Encoding UTF8
$content = $content.Replace('Day XX — 标题', "Day $dayNumber — $Title")
$content = $content.Replace('YYYY-MM-DD', (Get-Date -Format 'yyyy-MM-dd'))
Set-Content -LiteralPath $destination -Value $content -Encoding UTF8

Write-Output "Created: $destination"
