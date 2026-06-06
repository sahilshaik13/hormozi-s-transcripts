@echo off
setlocal
cd /d "%~dp0.."

if not exist "hormozi-brain\" (
  echo ERROR: hormozi-brain\ not found. Build the vault first.
  exit /b 1
)
if not exist "hormozi-index\" (
  echo ERROR: hormozi-index\ not found. Run: python tools\build_index.py
  exit /b 1
)

echo Staging vault + index for Render Docker build...
git add -f hormozi-brain hormozi-index

echo.
echo Done. Next steps:
echo   1. git commit -m "Add vault and index for Render deploy"
echo   2. git push
echo   3. Render Dashboard - redeploy
echo.
echo If git push fails (repo too large), use zip instead:
echo   scripts\pack_render_data.bat
echo   git add -f render-data.zip
echo   git commit -m "Add Render data bundle" ^&^& git push
echo.
echo Keep this repo PRIVATE — contains copyrighted Hormozi content.
endlocal
