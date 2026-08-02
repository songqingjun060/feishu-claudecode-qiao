@echo off
setlocal

if /I "%~1"=="/?" goto :help
if /I "%~1"=="--help" goto :help

cd /d "%~dp0"
title Feishu ClaudeCode Qiao Bridge

echo Starting Feishu ClaudeCode Qiao Bridge in foreground...
echo Project: %CD%
echo.
echo Press Ctrl+C in the PowerShell window to stop the bridge.
echo.

where powershell.exe >nul 2>nul
if errorlevel 1 (
    echo powershell.exe was not found.
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0run_foreground.ps1" -Restart
set EXIT_CODE=%ERRORLEVEL%

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Bridge startup command exited with code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%

:help
echo Usage: start_qiao.cmd
echo.
echo Opens a foreground PowerShell window and runs:
echo   run_foreground.ps1 -Restart
echo.
echo No arguments are required.
exit /b 0
