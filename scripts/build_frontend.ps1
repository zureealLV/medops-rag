param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $repo "frontend"
Set-Location $frontend

if (-not $SkipInstall) {
    npm ci
}
npm run typecheck
npm run build

Write-Host "Vue production bundle: $(Join-Path $frontend 'dist/index.html')"
