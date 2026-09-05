$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
& ".\.venv\Scripts\python.exe" -m ruff check app tests scripts evals experiments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& ".\.venv\Scripts\python.exe" -m pytest
exit $LASTEXITCODE
