@echo off
build_env\Scripts\python -m PyInstaller --onefile --noconsole --clean "bmw_dashboard.py"
pause
