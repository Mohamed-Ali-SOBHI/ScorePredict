param(
    [string]$DateFrom = "",
    [string]$DateTo = "",
    [string]$Portfolio = "",
    [int]$TrainMaxSeason = 0,
    [int]$DataSeason = 0,
    [double]$BankrollEur = 50.0,
    [string]$PythonExe = $env:SCOREPREDICT_PYTHON,
    [switch]$RefreshRawData
)

function Get-PredictionWindow {
    $today = (Get-Date).Date
    return @{
        DateFrom = $today.ToString("yyyy-MM-dd")
        DateTo = $today.AddDays(21).ToString("yyyy-MM-dd")
    }
}

if (-not $DateFrom -or -not $DateTo) {
    $window = Get-PredictionWindow
    if (-not $DateFrom) { $DateFrom = $window.DateFrom }
    if (-not $DateTo) { $DateTo = $window.DateTo }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$runner = Join-Path $scriptDir "run_upcoming_portfolio.ps1"

$argsList = @(
    "-ExecutionPolicy", "Bypass",
    "-File", $runner,
    "-DateFrom", $DateFrom,
    "-DateTo", $DateTo,
    "-Portfolio", $Portfolio,
    "-TrainMaxSeason", $TrainMaxSeason,
    "-DataSeason", $DataSeason,
    "-BankrollEur", $BankrollEur
)
if ($PythonExe) {
    $argsList += @("-PythonExe", $PythonExe)
}
if ($RefreshRawData) {
    $argsList += "-RefreshRawData"
}

powershell @argsList
