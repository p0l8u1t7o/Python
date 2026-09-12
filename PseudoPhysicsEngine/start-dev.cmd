@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-dev.ps1" -OpenBrowser %*
if errorlevel 1 pause
endlocal
