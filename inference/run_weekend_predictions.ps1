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
    $windowJson = & $PythonExe -m inference.prediction_window
    if ($LASTEXITCODE -ne 0) { throw "La fenetre de 24 heures est invalide." }
    return $windowJson | ConvertFrom-Json
}

if (-not $PythonExe) { $PythonExe = (Get-Command python -ErrorAction Stop).Source }
$next24Hours = -not $DateFrom -and -not $DateTo
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
if ($next24Hours) { $argsList += "-Next24Hours" }

powershell @argsList
exit $LASTEXITCODE
