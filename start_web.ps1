param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$Install,
    [switch]$NoReload,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
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

$PythonCmd = Resolve-Python
$PythonExe = $PythonCmd.Exe
$PythonArgs = $PythonCmd.Args

if ($Install) {
    Write-Host "Installing dependencies from requirements.txt..."
    & $PythonExe @PythonArgs -m pip install -r requirements.txt
}

Write-Host "Checking runtime dependencies..."
& $PythonExe @PythonArgs -c "import fastapi, uvicorn, langgraph; print('runtime dependencies ok')"

$EnvPath = Join-Path $ProjectRoot "20-multi-agent-debate\.env"
if (-not (Test-Path $EnvPath)) {
    Write-Warning "20-multi-agent-debate\.env was not found. The Web UI can start, but real review jobs need LLM API settings."
}

$FrontendDist = Join-Path $ProjectRoot "frontend\dist\index.html"
if (Test-Path $FrontendDist) {
    Write-Host "React build detected. FastAPI will serve frontend/dist."
} else {
    Write-Host "React build not found. Use frontend npm run dev for the React UI during development."
}

if ($CheckOnly) {
    Write-Host "Startup checks completed."
    exit 0
}

$Url = "http://${HostName}:${Port}"
Write-Host "Starting AI paper reviewer Web UI..."
Write-Host "Open $Url"

$UvicornArgs = @("-m", "uvicorn", "paper_reviewer.web:app", "--host", $HostName, "--port", "$Port")
if (-not $NoReload) {
    $UvicornArgs += "--reload"
}

& $PythonExe @PythonArgs @UvicornArgs
