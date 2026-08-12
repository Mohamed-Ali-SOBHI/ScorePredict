param(
    [string]$FreezeDate = "",
    [string]$Portfolio = "",
    [string]$Ledger = ".\inference\output\live_portfolio_bet_log.csv",
    [string]$Output = ".\inference\output\live_portfolio_evaluation.csv",
    [string]$SummaryOutput = ".\inference\output\live_portfolio_evaluation_summary.json",
    [switch]$RefreshRawData,
    [switch]$UpdateLedger
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
    if ($RefreshRawData) {
        python .\data_pipeline\scrapper.py --seasons 2025
        Assert-LastExitCode "data_pipeline\scrapper.py"
        python .\data_pipeline\enrich_data.py --data-dir .\Data
        Assert-LastExitCode "data_pipeline\enrich_data.py"
    }

    $command = @(
        "python",
        ".\inference\evaluate_live_portfolio.py",
        "--ledger", $Ledger,
        "--output", $Output,
        "--summary-output", $SummaryOutput
    )
    if ($FreezeDate) {
        $command += @("--freeze-date", $FreezeDate)
    }
    if ($Portfolio) {
        $command += @("--portfolio", $Portfolio)
    }
    if ($UpdateLedger) {
        $command += "--update-ledger"
    }

    & $command[0] $command[1..($command.Length - 1)]
    Assert-LastExitCode "evaluate_live_portfolio.py"
}
finally {
    Pop-Location
}
