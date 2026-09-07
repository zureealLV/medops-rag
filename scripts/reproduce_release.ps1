param(
    [switch]$Full
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"
$generated = Join-Path $repo "reports\generated\release"
New-Item -ItemType Directory -Force -Path $generated | Out-Null
Set-Location $repo

function Invoke-PythonStep {
    param([Parameter(Position = 0, ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python step failed: $($Arguments -join ' ')" }
}

Invoke-PythonStep @("-m", "ruff", "check", "app", "tests", "scripts", "evals", "experiments")
Invoke-PythonStep @("-m", "pytest", "-q")
Invoke-PythonStep @(".\evals\run_eval.py")
Invoke-PythonStep @(
    ".\evals\benchmark_ingestion.py", "--repeats", "1",
    "--output", "$generated\ingestion.json"
)
Invoke-PythonStep @(
    ".\evals\benchmark_retrieval.py", "--output", "$generated\retrieval.json"
)

if ($Full) {
    Invoke-PythonStep @(
        ".\evals\evaluate_confidence_thresholds.py",
        "--output", "$generated\confidence-calibration.json"
    )
    Invoke-PythonStep @(
        ".\evals\benchmark_v2_performance.py", "--answer-cases", "30", "--rerank-cases", "20",
        "--output", "$generated\performance.json"
    )
}

$outputs = @("ingestion.json", "retrieval.json")
if ($Full) { $outputs += @("confidence-calibration.json", "performance.json") }
$summary = [ordered]@{
    status = "pass"
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    mode = if ($Full) { "full" } else { "core" }
    python = (& $python --version 2>&1 | Out-String).Trim()
    outputs = $outputs
}
$summary | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 "$generated\summary.json"
$summary | ConvertTo-Json -Depth 4
