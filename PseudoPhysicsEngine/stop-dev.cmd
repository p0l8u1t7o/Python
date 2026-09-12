@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop-dev.ps1" %*
if errorlevel 1 pause
endlocal
