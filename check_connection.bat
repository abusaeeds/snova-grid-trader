@echo off
REM Read-only MT5 connection check (places no orders)
cd /d "%~dp0"
python -m pip install -q MetaTrader5
python check_connection.py
echo.
pause
