param(
    [string]$Data = "dataset_home.csv",
    [string]$Bets = "output\\experimental_protocol_targeted_favorite_fix\\best_strategy_bets.csv",
    [string]$OutputDir = "output\\clv_timing_filter_protocol",
    [int]$StartValSeason = 2021,
    [int]$EndValSeason = 2024,
    [int]$MinValExamples = 500,
    [double]$MinValKeepRate = 0.60,
    [string]$Thresholds = "0.35,0.40,0.45,0.50",
    [double]$MinClvOddsDiff = 0.0,
    [switch]$IncludeAlgoFeatures,
    [int]$NIterations = 160,
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
        ".\clv_timing_filter_protocol.py",
        "--data", $Data,
        "--bets", $Bets,
        "--output-dir", $OutputDir,
        "--start-val-season", $StartValSeason,
        "--end-val-season", $EndValSeason,
        "--min-val-examples", $MinValExamples,
        "--min-val-keep-rate", $MinValKeepRate,
        "--thresholds", $Thresholds,
        "--min-clv-odds-diff", $MinClvOddsDiff,
        "--n-iterations", $NIterations,
        "--bootstrap-iterations", $BootstrapIterations
    )
    if ($IncludeAlgoFeatures) {
        $arguments += "--include-algo-features"
    }

    & $Python @arguments
    Assert-LastExitCode "clv_timing_filter_protocol.py"
}
finally {
    Pop-Location
}
