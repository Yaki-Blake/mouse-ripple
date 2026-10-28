@echo off
chcp 65001 >nul 2>nul
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo [ERROR] Python was not found in PATH.
  echo         Install Python 3 first, then run this file again.
  echo.
  pause
  exit /b 1
)

python "%~dp0ripple-inject.py" %*

endlocal
