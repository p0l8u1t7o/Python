@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo   找不到 .venv，請先執行 setup.bat
  pause
  exit /b 1
)
".venv\Scripts\python.exe" run.py %*
if errorlevel 1 pause
