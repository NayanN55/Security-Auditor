param(
    [int]$Port = 8012,
    [string]$TestCase = "test1",
    [switch]$Live
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

function Test-PortFree {
    param([int]$CandidatePort)

    $activePorts = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().
        GetActiveTcpListeners().Port
    return -not ($activePorts -contains $CandidatePort)
}

function Get-AvailablePort {
    param([int]$PreferredPort)

    if (Test-PortFree -CandidatePort $PreferredPort) {
        return $PreferredPort
    }

    $fallback = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $fallback.Start()
    try {
        return $fallback.LocalEndpoint.Port
    } finally {
        $fallback.Stop()
    }
}

$python = Get-PythonCommand
$serverPort = Get-AvailablePort -PreferredPort $Port
$artifactsDir = Join-Path $root "artifacts"
if (-not (Test-Path $artifactsDir)) {
    New-Item -ItemType Directory -Path $artifactsDir | Out-Null
}
$offlineArtifactsDir = Join-Path $artifactsDir "offline"
if (-not (Test-Path $offlineArtifactsDir)) {
    New-Item -ItemType Directory -Path $offlineArtifactsDir | Out-Null
}

$exportArgs = @("app.py", "export")
if (-not $Live) {
    $exportArgs += @("--offline", "--demo-drift")
}
$exportArgs += @("--test-case", $TestCase)

& $python @exportArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$offlineExportArgs = @(
    "app.py",
    "export",
    "--offline",
    "--demo-drift",
    "--test-case",
    $TestCase,
    "--out-dir",
    $offlineArtifactsDir
)
& $python @offlineExportArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$stdoutLog = Join-Path $artifactsDir "server-$serverPort.log"
$stderrLog = Join-Path $artifactsDir "server-$serverPort.err"

$server = Start-Process `
    -FilePath $python `
    -ArgumentList @("-m", "http.server", "$serverPort") `
    -WorkingDirectory $root `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

Write-Output "Live URL: http://127.0.0.1:$serverPort/web/index.html"
Write-Output "Simulation URL: http://127.0.0.1:$serverPort/web/simulation.html"
Write-Output "Active test case: $TestCase"
Write-Output "Server PID: $($server.Id)"
Write-Output "Stop with: Stop-Process -Id $($server.Id)"
