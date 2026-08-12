param(
    [string]$Data = "dataset_home.csv",
    [string]$OutputDir = "output\model_benchmark_draw_models_fast",
    [int]$StartValSeason = 2021,
    [int]$EndValSeason = 2024,
    [int]$Trials = 1,
    [int]$NEstimators = 60,
    [int]$MinValBets = 20,
    [double]$MinValRoi = 0.02,
    [int]$MinTotalTestBets = 80,
    [int]$MaxNegativeFolds = 1,
    [string]$Python = "python",
    [switch]$SkipExisting
)

function Assert-LastExitCode([string]$StepName) {
    if ($LASTEXITCODE -ne 0) {
        throw "$StepName failed with exit code $LASTEXITCODE"
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptDir

try {
    $arguments = @(
        ".\experimental_protocol.py",
        "--data", $Data,
        "--output-dir", $OutputDir,
        "--profile", "wide",
        "--include-experiments", "draw_consensus_nonfavorite,logistic_draw_consensus_nonfavorite,extra_trees_draw_consensus_nonfavorite,hist_gradient_draw_consensus_nonfavorite",
        "--start-val-season", $StartValSeason,
        "--end-val-season", $EndValSeason,
        "--trials", $Trials,
        "--n-estimators", $NEstimators,
        "--min-val-bets", $MinValBets,
        "--min-val-roi", $MinValRoi,
        "--min-total-test-bets", $MinTotalTestBets,
        "--max-negative-folds", $MaxNegativeFolds,
        "--max-strategies", 4,
        "--test-fit-scope", "train",
        "--continue-on-error",
        "--python", $Python
    )
    if ($SkipExisting) {
        $arguments += "--skip-existing"
    }

    & $Python @arguments
    Assert-LastExitCode "model benchmark protocol"
}
finally {
    Pop-Location
}
