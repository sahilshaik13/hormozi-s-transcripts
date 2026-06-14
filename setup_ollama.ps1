# Hormozi Brain — Ollama setup (PowerShell)
# Run from anywhere:
#   & "F:\something_new\alex_hormozi\hormozi's transcripts\setup_ollama.ps1"

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=== Hormozi Brain: Ollama setup ===" -ForegroundColor Cyan
Write-Host "  Project: $PWD"
Write-Host ""

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example"
}

$envContent = Get-Content ".env" -Raw
if ($envContent -match "OLLAMA_API_KEY=your_key_here") {
    Write-Host "ERROR: Set OLLAMA_API_KEY in .env first." -ForegroundColor Red
    Write-Host "Get a key at https://ollama.com/settings/keys"
    exit 1
}

$python = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
$pip = Join-Path $PSScriptRoot "venv\Scripts\pip.exe"

if (-not (Test-Path $python)) {
    Write-Host "ERROR: venv not found. Create it first: python -m venv venv" -ForegroundColor Red
    exit 1
}

Write-Host "Installing Python dependencies (ollama + fastembed) ..."
& $pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Verifying server import ..."
& $python -c "from backend.server import app; print('OK:', app.title)"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Rebuilding search index with Ollama embeddings ..."
Write-Host "This may take several minutes."
& $python tools\build_index.py --rebuild
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "=== Setup complete ===" -ForegroundColor Green
Write-Host "Next: set OLLAMA_API_KEY on Render, then commit and push to redeploy."
