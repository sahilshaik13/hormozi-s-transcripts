@echo off
cd /d "%~dp0.."
if exist "venv\Scripts\activate.bat" call venv\Scripts\activate.bat
python tools\build_index.py --rebuild
