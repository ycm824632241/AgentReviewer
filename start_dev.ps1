param(
    [switch]$Install
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$FrontendRoot = Join-Path $ProjectRoot "frontend"

function Quote-ForPowerShell {
    param([string]$Value)
    return "'" + ($Value -replace "'", "''") + "'"
}

Set-Location $ProjectRoot

if ($Install) {
    Write-Host "Installing backend dependencies..."
    py -3.11 -m pip install -r requirements.txt

    Write-Host "Installing frontend dependencies..."
    Push-Location $FrontendRoot
    npm install
    Pop-Location
}

$BackendCommand = "Set-Location -LiteralPath $(Quote-ForPowerShell $ProjectRoot); .\start_web.ps1"
$FrontendCommand = "Set-Location -LiteralPath $(Quote-ForPowerShell $FrontendRoot); npm run dev"

Write-Host "Starting backend: http://127.0.0.1:8000"
Start-Process powershell -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $BackendCommand)

Write-Host "Starting frontend: http://localhost:5173"
Start-Process powershell -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $FrontendCommand)

Write-Host ""
Write-Host "Open http://localhost:5173 after the frontend window finishes starting."
