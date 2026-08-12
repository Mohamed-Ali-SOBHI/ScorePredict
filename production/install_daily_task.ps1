param(
    [string]$TaskName = "ScorePredict - Mise a jour quotidienne",
    [string]$At = "06:15",
    [string]$PythonExe = $env:SCOREPREDICT_PYTHON
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$runner = Join-Path $repoRoot "production\run_daily_update.ps1"
if (-not $PythonExe) {
    $bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    $PythonExe = if (Test-Path $bundledPython) { $bundledPython } else { (Get-Command python -ErrorAction Stop).Source }
}

$runAt = [datetime]::Today.Add([timespan]::Parse($At))
$arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runner`" -PythonExe `"$PythonExe`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $runAt
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Met a jour les clubs, les rencontres, les predictions et le site ScorePredict chaque jour." `
    -Force | Out-Null

Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
