@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    echo [INFO] Please install Python 3 first, then rerun this script.
    pause
    exit /b 1
)

echo [INFO] Installing Python dependencies for the Neko Web panel from Tsinghua mirror ...
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn -r "%~dp0panel_requirements.txt"

if errorlevel 1 (
    echo [ERROR] Failed to install Python dependencies.
    pause
    exit /b 1
)

echo [SUCCESS] Python dependencies installed.
pause
exit /b 0
