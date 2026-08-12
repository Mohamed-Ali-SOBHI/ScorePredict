param(
    [string]$PythonExe = $env:SCOREPREDICT_PYTHON,
    [int]$TrainMaxSeason = 0,
    [int]$DataSeason = 0,
    [double]$BankrollEur = 50.0
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$publisher = Join-Path $repoRoot "production\publish_dashboard.ps1"
$logDir = Join-Path $repoRoot "production\logs"
$lockPath = Join-Path $repoRoot "production\daily_update.lock"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

if (-not $PythonExe) {
    $bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    $PythonExe = if (Test-Path $bundledPython) { $bundledPython } else { (Get-Command python -ErrorAction Stop).Source }
}
if ($DataSeason -le 0) {
    $now = Get-Date
    $DataSeason = if ($now.Month -ge 7) { $now.Year } else { $now.Year - 1 }
}

$lockStream = $null
$transcriptStarted = $false
try {
    try {
        $lockStream = [System.IO.File]::Open(
            $lockPath,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
    }
    catch [System.IO.IOException] {
        Write-Output "Une mise à jour ScorePredict est déjà en cours."
        exit 0
    }

    $logPath = Join-Path $logDir ("daily-update-{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))
    Start-Transcript -Path $logPath -Append | Out-Null
    $transcriptStarted = $true
    Write-Output ("Mise à jour quotidienne démarrée à {0}" -f (Get-Date -Format "s"))

    powershell -NoProfile -ExecutionPolicy Bypass -File $publisher `
        -TrainMaxSeason $TrainMaxSeason `
        -DataSeason $DataSeason `
        -BankrollEur $BankrollEur `
        -PythonExe $PythonExe
    if ($LASTEXITCODE -ne 0) {
        throw "La mise à jour quotidienne a échoué ($LASTEXITCODE)."
    }
    Write-Output ("Mise à jour quotidienne terminée à {0}" -f (Get-Date -Format "s"))
}
finally {
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
    if ($lockStream) { $lockStream.Dispose() }
}
