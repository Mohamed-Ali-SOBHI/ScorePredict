param(
    [string]$Data = "dataset_home.csv",
    [string]$ExportSummary = "output\\positive_strategy_portfolio_summary.csv",
    [string]$ExportBets = "output\\positive_strategy_portfolio_bets.csv",
    [int]$Trials = 2,
    [string]$ModelVariants = "multiclass",
    [string]$Outcomes = "home_win,draw,away_win",
    [string]$PortfolioSelectionSplit = "val",
    [double]$SelectionMinRoi = 0.0,
    [int]$MaxStrategies = 4,
    [ValidateSet("pretest", "train")]
    [string]$TestFitScope = "train"
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
        python .\make_dataset.py
        Assert-LastExitCode "make_dataset.py"
    }

    python .\portfolio_strategy_search.py `
        --data $Data `
        --trials $Trials `
        --model-variants $ModelVariants `
        --outcomes $Outcomes `
        --portfolio-selection-split $PortfolioSelectionSplit `
        --selection-min-roi $SelectionMinRoi `
        --max-strategies $MaxStrategies `
        --test-fit-scope $TestFitScope `
        --export-summary $ExportSummary `
        --export-bets $ExportBets
    Assert-LastExitCode "portfolio_strategy_search.py"
}
finally {
    Pop-Location
}
