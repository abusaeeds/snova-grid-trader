@echo off
REM Opens the app in Demo mode (built-in simulator, no MetaTrader 5 needed)
cd /d "%~dp0"
python main.py --demo
