@echo off
REM Compiles the Windows installer (game + Tailscale).
REM Run build.bat FIRST so dist\ArtilleryDuel.exe exists for the installer to bundle.

set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo Inno Setup compiler not found.
  echo Install it with:  winget install JRSoftware.InnoSetup
  pause
  exit /b 1
)

if not exist "dist\ArtilleryDuel.exe" (
  echo dist\ArtilleryDuel.exe not found. Run build.bat first.
  pause
  exit /b 1
)

"%ISCC%" installer.iss
echo.
echo Done. Installer is at: dist\ArtilleryDuel-Setup.exe
pause
