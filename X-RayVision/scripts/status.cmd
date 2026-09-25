@echo off
chcp 65001 >nul
rem 開發用：status 平台服務；參數直接轉給 status.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0status.ps1" %*
exit /b %ERRORLEVEL%
