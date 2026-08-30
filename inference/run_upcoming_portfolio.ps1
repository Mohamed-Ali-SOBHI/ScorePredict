param(
    [string]$DateFrom,
    [string]$DateTo,
    [string]$FixturesCsv = "",
    [string]$Portfolio = "",
    [int]$TrainMaxSeason = 0,
    [int]$DataSeason = 0,
    [double]$BankrollEur = 50.0,
    [string]$PythonExe = $env:SCOREPREDICT_PYTHON,
    [string]$TrackingLedger = ".\\inference\\output\\live_portfolio_bet_log.csv",
    [switch]$RefreshRawData
)

function Assert-LastExitCode([string]$StepName) {
    if ($LASTEXITCODE -ne 0) {
        throw "$StepName failed with exit code $LASTEXITCODE"
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
Push-Location $repoRoot

try {
    if (-not $PythonExe) {
        $PythonExe = (Get-Command python -ErrorAction Stop).Source
    }
    if (-not $Portfolio) {
        $Portfolio = (& $PythonExe -c "from inference.portfolio_presets import DEFAULT_PORTFOLIO_NAME; print(DEFAULT_PORTFOLIO_NAME)").Trim()
        Assert-LastExitCode "resolve default portfolio"
    }
    if ($TrainMaxSeason -le 0) {
        $TrainMaxSeason = [int]((& $PythonExe -c "from inference.portfolio_presets import PRODUCTION_REFIT_TRAIN_MAX_SEASON; print(PRODUCTION_REFIT_TRAIN_MAX_SEASON)").Trim())
        Assert-LastExitCode "resolve production train season"
    }

    if ($DataSeason -le 0) {
        $now = Get-Date
        $DataSeason = if ($now.Month -ge 7) { $now.Year } else { $now.Year - 1 }
    }

    if ($RefreshRawData) {
        & $PythonExe .\data_pipeline\scrapper.py --seasons $DataSeason
        Assert-LastExitCode "data_pipeline\\scrapper.py"

        $catalogFrom = (Get-Date).Date.ToString("yyyy-MM-dd")
        $catalogTo = (Get-Date).Date.AddDays(60).ToString("yyyy-MM-dd")
        $catalogPath = ".\inference\output\current_season_fixture_catalog.csv"
        & $PythonExe .\inference\fetch_sportytrader_portfolio_odds.py `
            --date-from $catalogFrom `
            --date-to $catalogTo `
            --leagues "EPL,Bundesliga,Serie_A,Ligue_1,La_liga" `
            --allow-partial-leagues `
            --output $catalogPath
        Assert-LastExitCode "current season fixture catalog"

        & $PythonExe .\train\make_dataset.py --data-dir .\Data --output .\train\dataset_home.csv
        Assert-LastExitCode "train\\make_dataset.py"

        & $PythonExe -m data_pipeline.build_team_registry_from_fixtures `
            --fixtures-csv $catalogPath `
            --data-dir .\Data `
            --season $DataSeason `
            --historical-dataset .\train\dataset_home.csv
        Assert-LastExitCode "data_pipeline\\build_team_registry_from_fixtures.py"

        & $PythonExe -m data_pipeline.validate_team_registry `
            --data-dir .\Data `
            --season $DataSeason `
            --output .\train\output\team_registry_audit.json
        Assert-LastExitCode "data_pipeline\\validate_team_registry.py"
        & $PythonExe .\train\audit_data_quality.py `
            --data-dir .\Data `
            --dataset .\train\dataset_home.csv `
            --output-json .\train\output\data_quality_audit.json `
            --output-md .\train\output\data_quality_audit.md
        Assert-LastExitCode "train\\audit_data_quality.py"
    }

    if (-not $FixturesCsv) {
        $FixturesCsv = ".\\inference\\output\\sportytrader_upcoming_portfolio_odds.csv"
        & $PythonExe .\inference\fetch_sportytrader_portfolio_odds.py `
            --date-from $DateFrom `
            --date-to $DateTo `
            --portfolio $Portfolio `
            --allow-partial-leagues `
            --output $FixturesCsv
        Assert-LastExitCode "fetch_sportytrader_portfolio_odds.py"
    }

    & $PythonExe .\inference\predict_upcoming_portfolio.py `
        --fixtures-csv $FixturesCsv `
        --portfolio $Portfolio `
        --train-max-season $TrainMaxSeason `
        --bankroll-eur $BankrollEur `
        --tracking-ledger $TrackingLedger
    Assert-LastExitCode "predict_upcoming_portfolio.py"
}
finally {
    Pop-Location
}
