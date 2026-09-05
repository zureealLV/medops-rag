$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
& ".\.venv\Scripts\fastapi.exe" dev
