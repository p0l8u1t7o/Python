@echo off
chcp 65001 >nul
rem 開發用：stop 平台服務；參數直接轉給 stop.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1" %*
exit /b %ERRORLEVEL%
