@echo off
setlocal
cd /d "%~dp0.."

if not exist "hormozi-brain\" (
  echo ERROR: hormozi-brain\ not found.
  exit /b 1
)
if not exist "hormozi-index\" (
  echo ERROR: hormozi-index\ not found.
  exit /b 1
)

echo Creating render-data.zip ...
powershell -NoProfile -Command ^
  "Compress-Archive -Path 'hormozi-brain','hormozi-index' -DestinationPath 'render-data.zip' -Force"

echo.
echo Created render-data.zip
echo Next: git add -f render-data.zip
echo       git commit -m "Add Render data bundle"
echo       git push
echo.
echo Or upload render-data.zip to cloud storage and set BUILD_DATA_URL on Render.
endlocal
