@echo off
REM Builds dist\SNovaGridTrader\SNovaGridTrader.exe with PyInstaller
REM (the same engine auto-py-to-exe uses). Run from the project folder.
cd /d "%~dp0\.."
python -m pip install -r requirements-dev.txt
python -m PyInstaller --noconfirm --onedir --windowed ^
  --name "SNovaGridTrader" ^
  --icon "assets\logo.ico" ^
  --add-data "assets;assets" ^
  main.py
echo.
echo Done. Your app is in: dist\SNovaGridTrader\SNovaGridTrader.exe
pause
