@echo off
REM Build a single distributable .exe with the in-game auto-updater baked in.
REM Run this from the project folder after you have installed requirements:
REM     pip install -r requirements.txt pyinstaller
REM
REM The result is dist\ArtilleryDuel.exe  -- that single file is what you
REM upload to a GitHub release and what your friend runs.

py -m PyInstaller --noconfirm --onefile --windowed --name ArtilleryDuel main.py

echo.
echo Done. Your game is at: dist\ArtilleryDuel.exe
pause
