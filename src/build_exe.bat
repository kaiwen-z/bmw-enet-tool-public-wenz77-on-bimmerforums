@echo off
REM Build BMW_ENET_Dashboard.exe with PyInstaller.
REM First-time:  python -m pip install -r requirements.txt pyinstaller
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo Python not found on PATH. Install Python or add it to PATH.
    exit /b 1
)

echo Building BMW_ENET_Dashboard.exe (one-file, windowed)...
echo.

python -m PyInstaller ^
    --noconfirm ^
    --windowed ^
    --onefile ^
    --name BMW_ENET_Dashboard ^
    --collect-all matplotlib ^
    dashboard_launcher.py

if errorlevel 1 (
    echo.
    echo Build failed. Install deps:  python -m pip install -r requirements.txt pyinstaller
    pause
    exit /b 1
)

echo.
echo Done. Output: %~dp0dist\BMW_ENET_Dashboard.exe
echo.
pause
