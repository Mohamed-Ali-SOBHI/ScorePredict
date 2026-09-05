param(
    [string]$FixturesCsv = ".\inference\output\sportytrader_upcoming_portfolio_odds.csv",
    [int]$TrainMaxSeason = 2025,
    [double]$BankrollEur = 50.0,
    [string]$PythonExe = $env:SCOREPREDICT_PYTHON,
    [switch]$RetrainModels,
    [switch]$Strict
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$shadowRoot = Join-Path $scriptDir "output\shadow"
$statusPath = Join-Path $shadowRoot "shadow_portfolios_status.json"
$results = @()

Push-Location $repoRoot
try {
    if (-not $PythonExe) {
        $PythonExe = (Get-Command python -ErrorAction Stop).Source
    }
    $portfolioList = (& $PythonExe -c "from inference.portfolio_presets import SHADOW_PORTFOLIO_NAMES; print(','.join(SHADOW_PORTFOLIO_NAMES))").Trim()
    $portfolioNames = @($portfolioList -split ",")
    if ($LASTEXITCODE -ne 0 -or $portfolioNames.Count -eq 0) {
        throw "Impossible de charger les portefeuilles fantomes."
    }

    foreach ($portfolio in $portfolioNames) {
        $portfolio = $portfolio.Trim()
        if (-not $portfolio) { continue }
        $portfolioDir = Join-Path $shadowRoot $portfolio
        New-Item -ItemType Directory -Path $portfolioDir -Force | Out-Null
        $ledger = Join-Path $portfolioDir "live_portfolio_bet_log.csv"
        $allPredictions = Join-Path $portfolioDir "upcoming_portfolio_predictions.csv"
        $recommendedBets = Join-Path $portfolioDir "upcoming_portfolio_bets.csv"
        $evaluation = Join-Path $portfolioDir "live_portfolio_evaluation.csv"
        $summary = Join-Path $portfolioDir "live_portfolio_evaluation_summary.json"
        $storeStatus = Join-Path $portfolioDir "prediction_store_status.json"

        try {
            & $PythonExe -m inference.supabase_prediction_store pull `
                --ledger $ledger `
                --portfolio $portfolio `
                --status-output $storeStatus
            if ($LASTEXITCODE -ne 0) { throw "Lecture Supabase impossible ($LASTEXITCODE)." }

            $predictionArgs = @(
                ".\inference\predict_upcoming_portfolio.py",
                "--fixtures-csv", $FixturesCsv,
                "--portfolio", $portfolio,
                "--train-max-season", $TrainMaxSeason,
                "--bankroll-eur", $BankrollEur,
                "--tracking-ledger", $ledger,
                "--model-cache-dir", ".\inference\model_cache",
                "--output-all", $allPredictions,
                "--output-bets", $recommendedBets
            )
            if ($RetrainModels) { $predictionArgs += "--retrain-models" }
            & $PythonExe @predictionArgs
            if ($LASTEXITCODE -ne 0) { throw "Calcul fantome impossible ($LASTEXITCODE)." }

            & $PythonExe .\inference\evaluate_live_portfolio.py `
                --ledger $ledger `
                --data-dir .\Data `
                --freeze-date "2026-09-01" `
                --portfolio $portfolio `
                --output $evaluation `
                --summary-output $summary `
                --update-ledger
            if ($LASTEXITCODE -ne 0) { throw "Evaluation fantome impossible ($LASTEXITCODE)." }

            & $PythonExe -m inference.supabase_prediction_store push `
                --ledger $ledger `
                --portfolio $portfolio `
                --status-output $storeStatus
            if ($LASTEXITCODE -ne 0) { throw "Ecriture Supabase impossible ($LASTEXITCODE)." }

            $betCount = 0
            if (Test-Path $recommendedBets) {
                $betCount = @(Import-Csv -LiteralPath $recommendedBets).Count
            }
            $results += [pscustomobject]@{
                portfolio = $portfolio
                status = "ok"
                recommendations = $betCount
                public = $false
                real_stake = $false
                error = $null
            }
        }
        catch {
            Write-Warning "Portefeuille fantome $portfolio : $($_.Exception.Message)"
            $results += [pscustomobject]@{
                portfolio = $portfolio
                status = "failed"
                recommendations = 0
                public = $false
                real_stake = $false
                error = $_.Exception.Message
            }
        }
    }

    New-Item -ItemType Directory -Path $shadowRoot -Force | Out-Null
    $statusPayload = [ordered]@{
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        execution_mode = "shadow_no_publication_no_real_stake"
        portfolios = $results
    }
    $statusPayload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statusPath -Encoding utf8
    $statusPayload | ConvertTo-Json -Depth 5

    if ($Strict -and @($results | Where-Object { $_.status -ne "ok" }).Count -gt 0) {
        throw "Au moins un portefeuille fantome a echoue."
    }
}
finally {
    Pop-Location
}
