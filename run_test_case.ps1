param(
    [string]$Case = "test1",
    [int]$Port = 8012,
    [switch]$SkipServer
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Get-PythonCommand {
    $venvPython = Join-Path $root ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }

    return "python"
}

function Get-EnvValue {
    param([string]$Name)

    $envPath = Join-Path $root ".env"
    if (-not (Test-Path $envPath)) {
        return $null
    }

    $match = Select-String -Path $envPath -Pattern "^$Name=(.+)$" | Select-Object -First 1
    if ($null -eq $match) {
        return $null
    }

    return $match.Matches[0].Groups[1].Value.Trim()
}

$python = Get-PythonCommand
$awsProfile = Get-EnvValue -Name "AWS_PROFILE"
if ([string]::IsNullOrWhiteSpace($awsProfile)) {
    throw "AWS_PROFILE was not found in .env."
}

Write-Output "Applying test case '$Case' with AWS profile '$awsProfile'..."
terraform init -reconfigure -no-color | Out-Host
terraform apply `
    -auto-approve `
    -var="aws_profile=$awsProfile" `
    -var="seed_test_drift=true" `
    -var="test_case_name=$Case" `
    -no-color | Out-Host

if ($SkipServer) {
    & $python "app.py" "export" "--test-case" $Case
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    & $python "app.py" "export" "--offline" "--demo-drift" "--test-case" $Case "--out-dir" "artifacts\offline"
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    Write-Output "Test case applied and artifacts refreshed."
    Write-Output "Live artifacts: $root\artifacts"
    Write-Output "Offline artifacts: $root\artifacts\offline"
    exit 0
}

& ".\start_local.ps1" -Port $Port -Live -TestCase $Case
