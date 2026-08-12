param(
    [string]$Data = "dataset_home.csv",
    [string]$OutputDir = "output\\experimental_protocol",
    [ValidateSet("quick", "standard", "wide")]
    [string]$Profile = "standard",
    [string]$IncludeExperiments = "",
    [string]$ExcludeExperiments = "",
    [int]$StartValSeason = 2021,
    [int]$EndValSeason = 2024,
    [int]$Trials = 3,
    [int]$NEstimators = 350,
    [int]$MinValBets = 25,
    [double]$MinValRoi = 0.02,
    [int]$MinTotalTestBets = 80,
    [int]$MaxNegativeFolds = 1,
    [int]$MaxStrategies = 4,
    [ValidateSet("train", "pretest")]
    [string]$TestFitScope = "train",
    [switch]$IncludeAlgoFeatures,
    [switch]$IncludeClosingMarketFeatures,
    [switch]$IncludeConsensusMarketFeatures,
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
        $makeDatasetArguments = @(".\make_dataset.py")
        if ($IncludeClosingMarketFeatures) {
            $makeDatasetArguments += "--include-closing-market-data"
        }
        if ($IncludeConsensusMarketFeatures) {
            $makeDatasetArguments += "--include-consensus-market-data"
        }
        & $Python @makeDatasetArguments
        Assert-LastExitCode "make_dataset.py"
    }

    $arguments = @(
        ".\experimental_protocol.py",
        "--data", $Data,
        "--output-dir", $OutputDir,
        "--profile", $Profile,
        "--include-experiments", $IncludeExperiments,
        "--exclude-experiments", $ExcludeExperiments,
        "--start-val-season", $StartValSeason,
        "--end-val-season", $EndValSeason,
        "--trials", $Trials,
        "--n-estimators", $NEstimators,
        "--min-val-bets", $MinValBets,
        "--min-val-roi", $MinValRoi,
        "--min-total-test-bets", $MinTotalTestBets,
        "--max-negative-folds", $MaxNegativeFolds,
        "--max-strategies", $MaxStrategies,
        "--test-fit-scope", $TestFitScope,
        "--python", $Python
    )
    if ($IncludeAlgoFeatures) {
        $arguments += "--include-algo-features"
    }
    if ($IncludeClosingMarketFeatures) {
        $arguments += "--include-closing-market-features"
    }
    if ($IncludeConsensusMarketFeatures) {
        $arguments += "--include-consensus-market-features"
    }

    & $Python @arguments
    Assert-LastExitCode "experimental_protocol.py"
}
finally {
    Pop-Location
}
