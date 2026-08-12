param(
    [string]$DataDir = "..\\Data",
    [string]$Dataset = "dataset_home.csv",
    [string]$ProtocolDir = "output\\experimental_protocol_targeted_favorite_fix",
    [string]$OutputJson = "output\\data_quality_audit.json",
    [string]$OutputMd = "output\\data_quality_audit.md",
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
    & $Python .\audit_data_quality.py `
        --data-dir $DataDir `
        --dataset $Dataset `
        --protocol-dir $ProtocolDir `
        --output-json $OutputJson `
        --output-md $OutputMd
    Assert-LastExitCode "audit_data_quality.py"
}
finally {
    Pop-Location
}
