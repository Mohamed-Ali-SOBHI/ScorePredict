param(
    [string]$DateFrom = "",
    [string]$DateTo = "",
    [string]$Portfolio = "",
    [int]$TrainMaxSeason = 0,
    [int]$DataSeason = 0,
    [double]$BankrollEur = 50.0,
    [string]$PythonExe = $env:SCOREPREDICT_PYTHON,
    [switch]$SkipRawRefresh,
    [switch]$AllowStaleSnapshot
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Push-Location $repoRoot
try {
    if (-not $PythonExe) {
        $PythonExe = (Get-Command python -ErrorAction Stop).Source
    }
    if (-not $Portfolio) {
        $Portfolio = (& $PythonExe -c "from inference.portfolio_presets import DEFAULT_PORTFOLIO_NAME; print(DEFAULT_PORTFOLIO_NAME)").Trim()
        if ($LASTEXITCODE -ne 0) { throw "La selection du portefeuille de production a echoue ($LASTEXITCODE)." }
    }
    if ($TrainMaxSeason -le 0) {
        $TrainMaxSeason = [int]((& $PythonExe -c "from inference.portfolio_presets import PRODUCTION_REFIT_TRAIN_MAX_SEASON; print(PRODUCTION_REFIT_TRAIN_MAX_SEASON)").Trim())
        if ($LASTEXITCODE -ne 0) { throw "La selection de la saison d'entrainement a echoue ($LASTEXITCODE)." }
    }
    $ledger = ".\inference\output\live_portfolio_bet_log.csv"
    $evaluation = ".\inference\output\live_portfolio_evaluation.csv"
    $evaluationSummary = ".\inference\output\live_portfolio_evaluation_summary.json"
    $storeStatus = ".\inference\output\prediction_store_status.json"

    & $PythonExe -m inference.supabase_prediction_store pull `
        --ledger $ledger `
        --portfolio $Portfolio `
        --status-output $storeStatus
    if ($LASTEXITCODE -ne 0) { throw "La lecture de la mémoire des prévisions a échoué ($LASTEXITCODE)." }

    $runnerArgs = @(
        "-ExecutionPolicy", "Bypass",
        "-File", ".\inference\run_weekend_predictions.ps1",
        "-Portfolio", $Portfolio,
        "-TrainMaxSeason", $TrainMaxSeason,
        "-DataSeason", $DataSeason,
        "-BankrollEur", $BankrollEur
    )
    $runnerArgs += @("-PythonExe", $PythonExe)
    if ($DateFrom) { $runnerArgs += @("-DateFrom", $DateFrom) }
    if ($DateTo) { $runnerArgs += @("-DateTo", $DateTo) }
    if (-not $SkipRawRefresh) { $runnerArgs += "-RefreshRawData" }

    powershell @runnerArgs
    if ($LASTEXITCODE -ne 0) { throw "Le calcul des prédictions a échoué ($LASTEXITCODE)." }

    & $PythonExe .\inference\evaluate_live_portfolio.py `
        --ledger $ledger `
        --data-dir .\Data `
        --portfolio $Portfolio `
        --output $evaluation `
        --summary-output $evaluationSummary `
        --update-ledger
    if ($LASTEXITCODE -ne 0) { throw "La vérification des résultats a échoué ($LASTEXITCODE)." }

    & $PythonExe -m inference.supabase_prediction_store push `
        --ledger $ledger `
        --portfolio $Portfolio `
        --status-output $storeStatus
    if ($LASTEXITCODE -ne 0) { throw "L'enregistrement de la mémoire a échoué ($LASTEXITCODE)." }

    $snapshotArgs = @("-m", "production.export_snapshot")
    if ($AllowStaleSnapshot) { $snapshotArgs += "--allow-stale" }
    & $PythonExe @snapshotArgs
    if ($LASTEXITCODE -ne 0) { throw "La publication du snapshot a échoué ($LASTEXITCODE)." }
}
finally {
    Pop-Location
}
