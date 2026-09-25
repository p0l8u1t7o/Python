@echo off
chcp 65001 >nul
rem 開發用：start 平台服務；參數直接轉給 start.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
exit /b %ERRORLEVEL%
