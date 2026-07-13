param(
    [string]$BackendHost = "127.0.0.1",
    [int]$BackendPort = 8000,
    [string]$FrontendHost = "localhost",
    [int]$FrontendPort = 5173,
    [switch]$Install,
    [switch]$NoOpen,
    [switch]$NoReload
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$FrontendRoot = Join-Path $ProjectRoot "frontend"
$BackendScript = Join-Path $ProjectRoot "start_web.ps1"
Set-Location $ProjectRoot

function Resolve-Python {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        & py -3.11 -c "import sys" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return @{ Exe = "py"; Args = @("-3.11") }
        }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @{ Exe = "python"; Args = @() }
    }

    throw "Python was not found. Install Python 3.11, then rerun this script."
}

function Resolve-Npm {
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npm) {
        throw "npm was not found. Install Node.js/npm, then rerun this script."
    }

    return $npm.Source
}

function Quote-ForPowerShell {
    param([string]$Value)
    return "'" + ($Value -replace "'", "''") + "'"
}

function Assert-LastExitCode {
    param([string]$CommandName)

    if ($LASTEXITCODE -ne 0) {
        throw "$CommandName failed with exit code $LASTEXITCODE."
    }
}

Write-Host "Checking Python and npm..."
$PythonCmd = Resolve-Python
$NpmExe = Resolve-Npm
& $NpmExe --version | Out-Null
Assert-LastExitCode "npm --version"

if ($Install) {
    Write-Host "Installing Python dependencies..."
    & $PythonCmd.Exe @($PythonCmd.Args) -m pip install -r (Join-Path $ProjectRoot "requirements.txt")
    Assert-LastExitCode "pip install"

    Write-Host "Installing frontend dependencies..."
    Push-Location $FrontendRoot
    try {
        & $NpmExe install
        Assert-LastExitCode "npm install"
    } finally {
        Pop-Location
    }
}

$EnvPath = Join-Path $ProjectRoot "20-multi-agent-debate\.env"
if (-not (Test-Path $EnvPath)) {
    Write-Warning "20-multi-agent-debate\.env was not found. The Web UI can start, but real review jobs need LLM API settings."
}

Write-Host "Running backend startup checks..."
$BackendCheckArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $BackendScript,
    "-HostName", $BackendHost,
    "-Port", "$BackendPort",
    "-CheckOnly"
)
if ($NoReload) {
    $BackendCheckArgs += "-NoReload"
}
& powershell @BackendCheckArgs
Assert-LastExitCode "backend startup checks"

$BackendCommandParts = @(
    "Set-Location -LiteralPath $(Quote-ForPowerShell $ProjectRoot)",
    "& $(Quote-ForPowerShell $BackendScript) -HostName $(Quote-ForPowerShell $BackendHost) -Port $BackendPort"
)
if ($NoReload) {
    $BackendCommandParts[1] += " -NoReload"
}
$BackendCommand = $BackendCommandParts -join "; "
$BackendArgs = @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-Command", $BackendCommand
)

$FrontendCommand = @(
    "`$env:VITE_BACKEND_PROXY_TARGET = $(Quote-ForPowerShell "http://${BackendHost}:${BackendPort}")",
    "Set-Location -LiteralPath $(Quote-ForPowerShell $FrontendRoot)",
    "& $(Quote-ForPowerShell $NpmExe) run dev -- --host $(Quote-ForPowerShell $FrontendHost) --port $FrontendPort"
) -join "; "
$FrontendArgs = @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-Command", $FrontendCommand
)

$FrontendUrl = "http://${FrontendHost}:${FrontendPort}"

Write-Host "Starting FastAPI backend at http://${BackendHost}:${BackendPort} ..."
Start-Process powershell -ArgumentList $BackendArgs -WorkingDirectory $ProjectRoot

Write-Host "Starting Vite frontend at $FrontendUrl ..."
Start-Process powershell -ArgumentList $FrontendArgs -WorkingDirectory $FrontendRoot

if (-not $NoOpen) {
    Write-Host "Opening $FrontendUrl ..."
    Start-Process $FrontendUrl
} else {
    Write-Host "Open $FrontendUrl when both windows finish starting."
}
