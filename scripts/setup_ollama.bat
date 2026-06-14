@echo off
setlocal
cd /d "%~dp0.."

echo === Hormozi Brain: Ollama setup ===
echo   Project: %CD%
echo.
echo   PowerShell:  .\setup_ollama.ps1     (from project root)
echo   PowerShell:  .\setup_ollama.bat     (needs .\ prefix)
echo   CMD:         setup_ollama.bat
echo.

if not exist ".env" (
  echo Copying .env.example to .env ...
  copy /Y .env.example .env >nul
)

findstr /B "OLLAMA_API_KEY=your_key_here" .env >nul 2>&1
if not errorlevel 1 (
  echo ERROR: Set OLLAMA_API_KEY in .env first.
  echo Get a key at https://ollama.com/settings/keys
  exit /b 1
)

if exist "venv\Scripts\activate.bat" call venv\Scripts\activate.bat

echo Installing Python dependencies ...
python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

echo.
echo Verifying server import ...
python -c "from backend.server import app; print('OK:', app.title)"
if errorlevel 1 exit /b 1

echo.
echo Rebuilding search index with Ollama embeddings ...
echo This may take several minutes.
python tools\build_index.py --rebuild
if errorlevel 1 exit /b 1

echo.
echo === Setup complete ===
echo Next: set OLLAMA_API_KEY on Render, then commit and push to redeploy.
