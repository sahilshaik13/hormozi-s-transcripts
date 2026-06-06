@echo off
setlocal
cd /d "%~dp0.."

echo Starting Hormozi Brain web stack...
echo   API:  http://127.0.0.1:8000
echo   UI:   http://127.0.0.1:5173
echo.

if exist "venv\Scripts\activate.bat" call venv\Scripts\activate.bat

start "Hormozi API" cmd /k python -m uvicorn backend.server:app --reload --host 127.0.0.1 --port 8000

if exist "web\node_modules\" (
  start "Hormozi Web" cmd /k cd /d "%~dp0..\web" ^& npm run dev
) else (
  echo Installing web dependencies...
  cd web
  call npm install
  if errorlevel 1 exit /b 1
  start "Hormozi Web" cmd /k npm run dev
)

echo Done. Two terminal windows opened.
