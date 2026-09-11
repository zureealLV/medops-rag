param(
    [string]$EnvFile
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$loadedNames = @()
$previousValues = @{}

if ($EnvFile) {
    $resolvedEnvFile = (Resolve-Path -LiteralPath $EnvFile).Path
    $allowedNames = @(
        "MODEL_API_KEY", "DEEPSEEK_API_KEY", "MODEL_BASE_URL", "MODEL_NAME",
        "MODEL_TIMEOUT_SECONDS", "MODEL_MAX_RETRIES", "MODEL_MAX_CONCURRENCY",
        "MODEL_MAX_QUEUE_WAITERS", "MODEL_QUEUE_TIMEOUT_SECONDS",
        "MODEL_OVERLOAD_RETRY_AFTER_SECONDS"
    )
    foreach ($line in Get-Content -LiteralPath $resolvedEnvFile -Encoding utf8) {
        if ($line -notmatch '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') { continue }
        $name = $Matches[1]
        if ($name -notin $allowedNames) { continue }
        $value = $Matches[2].Trim().Trim('"').Trim("'")
        $previousValues[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
        $loadedNames += $name
    }
    if (
        "MODEL_API_KEY" -notin $loadedNames -and
        "DEEPSEEK_API_KEY" -notin $loadedNames
    ) {
        throw "Env file does not contain MODEL_API_KEY or DEEPSEEK_API_KEY"
    }
}

try {
    & ".\.venv\Scripts\fastapi.exe" dev
}
finally {
    foreach ($name in $loadedNames) {
        [Environment]::SetEnvironmentVariable($name, $previousValues[$name], "Process")
    }
}
