@echo off
setlocal
cd /d "%~dp0.."

if exist "venv\Scripts\activate.bat" call venv\Scripts\activate.bat

if not exist "web\dist\index.html" (
  echo Building frontend...
  cd web
  call npm install
  call npm run build
  cd ..
)

echo Starting production server at http://127.0.0.1:8000
python -m uvicorn backend.server:app --host 127.0.0.1 --port 8000
