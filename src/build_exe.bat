@echo off
REM Build BMW_ENET_Dashboard.exe with PyInstaller.
REM First-time:  python -m pip install -r requirements.txt pyinstaller
REM
REM Size notes:
REM   - Do NOT use --collect-all matplotlib (adds huge unused chunks).
REM   - Use a clean venv with only requirements.txt + pyinstaller for a smaller tree.
REM   - For another ~10-20%% less, switch --onefile to onedir (many files, no single huge exe).
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo Python not found on PATH. Install Python or add it to PATH.
    exit /b 1
)

echo Building BMW_ENET_Dashboard.exe (one-file, windowed, trimmed deps)...
echo.

python -m PyInstaller ^
    --noconfirm ^
    --windowed ^
    --onefile ^
    --name BMW_ENET_Dashboard ^
    --exclude-module matplotlib.tests ^
    --exclude-module numpy.tests ^
    --exclude-module pandas.tests ^
    --exclude-module scipy ^
    --exclude-module PyQt5 ^
    --exclude-module PyQt6 ^
    --exclude-module PySide2 ^
    --exclude-module PySide6 ^
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
