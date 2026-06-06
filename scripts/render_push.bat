@echo off
setlocal
cd /d "%~dp0.."

echo === Hormozi Brain: prepare + push for Render ===
echo.

if not exist "hormozi-brain\" (
  echo ERROR: hormozi-brain\ missing
  exit /b 1
)
if not exist "hormozi-index\" (
  echo ERROR: hormozi-index\ missing - run: python tools\build_index.py
  exit /b 1
)

if not exist "render-data.zip" (
  echo Creating render-data.zip ...
  powershell -NoProfile -Command "Compress-Archive -Path 'hormozi-brain','hormozi-index' -DestinationPath 'render-data.zip' -Force"
)

echo Staging deploy files...
git add Dockerfile render.yaml requirements.prod.txt scripts/render_install_data.sh scripts/pack_render_data.bat scripts/stage_for_render.bat scripts/render_push.bat
git add -f render-data.zip

echo.
echo Files staged. Now run:
echo   git commit -m "Render deploy: fixed Dockerfile + data bundle"
echo   git push
echo.
echo Then in Render: Manual Deploy ^> Clear build cache ^> Deploy
echo.
pause
endlocal
