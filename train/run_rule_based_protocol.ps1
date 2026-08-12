param(
    [string]$Data = "dataset_home.csv",
    [string]$OutputDir = "output\\rule_based_draw_protocol",
    [string]$IncludeCategories = "",
    [string]$IncludeBetLeagues = "",
    [string]$ExcludeBetLeagues = "",
    [string]$IncludeDataLeagues = "",
    [string]$ExcludeDataLeagues = "",
    [int]$StartValSeason = 2021,
    [int]$EndValSeason = 2024,
    [int]$MinValBets = 25,
    [double]$MinValRoi = 0.02,
    [int]$MaxStrategies = 4,
    [double]$MaxValOverlap = 0.35,
    [double]$SelectionMinRoi = 0.0,
    [int]$MinTotalTestBets = 80,
    [int]$MaxNegativeFolds = 1,
    [string]$Python = "python"
)

function Assert-LastExitCode([string]$StepName) {
    if ($LASTEXITCODE -ne 0) {
        throw "$StepName failed with exit code $LASTEXITCODE"
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptDir

try {
    if (-not (Test-Path $Data)) {
        & $Python .\make_dataset.py
        Assert-LastExitCode "make_dataset.py"
    }

    $arguments = @(
        ".\rule_based_strategy_search.py",
        "--data", $Data,
        "--output-dir", $OutputDir,
        "--start-val-season", $StartValSeason,
        "--end-val-season", $EndValSeason,
        "--min-val-bets", $MinValBets,
        "--min-val-roi", $MinValRoi,
        "--max-strategies", $MaxStrategies,
        "--max-val-overlap", $MaxValOverlap,
        "--selection-min-roi", $SelectionMinRoi,
        "--min-total-test-bets", $MinTotalTestBets,
        "--max-negative-folds", $MaxNegativeFolds
    )

    if ($IncludeCategories) {
        $arguments += @("--include-categories", $IncludeCategories)
    }
    if ($IncludeBetLeagues) {
        $arguments += @("--include-bet-leagues", $IncludeBetLeagues)
    }
    if ($ExcludeBetLeagues) {
        $arguments += @("--exclude-bet-leagues", $ExcludeBetLeagues)
    }
    if ($IncludeDataLeagues) {
        $arguments += @("--include-data-leagues", $IncludeDataLeagues)
    }
    if ($ExcludeDataLeagues) {
        $arguments += @("--exclude-data-leagues", $ExcludeDataLeagues)
    }

    & $Python @arguments
    Assert-LastExitCode "rule_based_strategy_search.py"
}
finally {
    Pop-Location
}
