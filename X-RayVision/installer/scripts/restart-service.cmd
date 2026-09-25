@echo off
chcp 65001 >nul
rem X-RayVision 服務控制：restart（需要系統管理員權限時會自動要求提升）
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0service-control.ps1" -Action restart %*
exit /b %ERRORLEVEL%
