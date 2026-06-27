@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0NekoLauncher.ps1" %*
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
    echo.
    echo [ERROR] NekoLauncher failed with code %ERR%.
    pause
)
exit /b %ERR%
