@echo off
cd /d "%~dp0"
where pwsh >nul 2>&1
if %errorlevel%==0 (
    pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
)
if errorlevel 1 pause
