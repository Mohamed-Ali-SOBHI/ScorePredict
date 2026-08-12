param(
    [string]$Data = "dataset_home.csv",
    [string]$Bets = "output\\experimental_protocol_targeted_favorite_fix\\best_strategy_bets_with_clv.csv",
    [string]$TimingScores = "output\\clv_timing_filter_draw_consensus_conservative_keep\\scored_bets.csv",
    [string]$Summary = "output\\experimental_protocol_targeted_favorite_fix\\selected_strategies.csv",
    [string]$OutputDir = "output\\meta_filter_draw_consensus_no_timing_full",
    [int]$StartValSeason = 2021,
    [int]$EndValSeason = 2024,
    [int]$MinTrainBets = 80,
    [int]$MinValBets = 70,
    [double]$MinValKeepRate = 0.50,
    [string]$Thresholds = "auto",
    [ValidateSet("win", "positive_clv", "win_and_positive_clv")]
    [string]$Target = "win",
    [switch]$IncludeTimingScore,
    [switch]$NoOpeningContext,
    [switch]$IncludeAlgoFeatures,
    [switch]$SkipScientificReport,
    [int]$NIterations = 120,
    [int]$BootstrapIterations = 5000,
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
        & $Python .\make_dataset.py --include-closing-market-data --include-consensus-market-data
        Assert-LastExitCode "make_dataset.py"
    }

    $arguments = @(
        ".\meta_filter_protocol.py",
        "--data", $Data,
        "--bets", $Bets,
        "--timing-scores", $TimingScores,
        "--output-dir", $OutputDir,
        "--start-val-season", $StartValSeason,
        "--end-val-season", $EndValSeason,
        "--min-train-bets", $MinTrainBets,
        "--min-val-bets", $MinValBets,
        "--min-val-keep-rate", $MinValKeepRate,
        "--thresholds", $Thresholds,
        "--target", $Target,
        "--n-iterations", $NIterations,
        "--bootstrap-iterations", $BootstrapIterations
    )
    if ($IncludeTimingScore) {
        $arguments += "--include-timing-score"
    }
    else {
        $arguments += "--no-include-timing-score"
    }
    if ($NoOpeningContext) {
        $arguments += "--no-include-opening-context"
    }
    if ($IncludeAlgoFeatures) {
        $arguments += "--include-algo-features"
    }

    & $Python @arguments
    Assert-LastExitCode "meta_filter_protocol.py"

    if (-not $SkipScientificReport) {
        $filteredBets = Join-Path $OutputDir "filtered_bets.csv"
        if (Test-Path $filteredBets) {
            & $Python .\scientific_validation_report.py `
                --bets $filteredBets `
                --summary $Summary `
                --bootstrap-iterations $BootstrapIterations `
                --output-md (Join-Path $OutputDir "filtered_bets_scientific_report.md") `
                --output-json (Join-Path $OutputDir "filtered_bets_scientific_report.json") `
                --output-bets-clv (Join-Path $OutputDir "filtered_bets_with_clv.csv")
            Assert-LastExitCode "scientific_validation_report.py"
        }
    }
}
finally {
    Pop-Location
}
