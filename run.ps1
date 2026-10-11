param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
$rmsPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $rmsPython)) {
    throw '请先按“README.md”安装独立环境。'
}
Push-Location -LiteralPath $PSScriptRoot
try {
    & $rmsPython -m uvicorn v3.api:app --host 127.0.0.1 --port $Port
} finally {
    Pop-Location
}
