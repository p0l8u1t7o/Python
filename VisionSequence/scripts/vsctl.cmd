@echo off
rem VisionSequence station command line (checkout / release tree). The install root gets its own vsctl.cmd
rem that always points at current\scripts\vsctl.ps1. Usage: scripts\vsctl status | logs | doctor | ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0vsctl.ps1" %*
