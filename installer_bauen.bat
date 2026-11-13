@echo off
rem ============================================================
rem  CardMaster LS.exe bauen (eigenstaendig, ohne Python-Installation)
rem  Aufruf:  installer_bauen.bat
rem
rem  Erzeugt zuerst Programm-Icon und Assistenten-Grafiken neu aus
rem  dem Ordner assets. Baut dann aus "installer\CardMaster LS.spec".
rem  In der Spec sind Formular (Spesen.pdf), Programm-Symbol, der
rem  Ordner assets (Logos/Symbole) und die Anleitung als
rem  mitgelieferte Dateien eingetragen.
rem ============================================================
cd /d "%~dp0"
echo Programm-Icon aus den Assets erzeugen ...
py "%~dp0installer\installer_icon.py"
if errorlevel 1 (
  echo FEHLER beim Erzeugen des Programm-Icons.
  pause
  exit /b 1
)
echo Assistenten-Grafiken aus den Assets erzeugen ...
py "%~dp0installer\installer_grafiken.py"
if errorlevel 1 (
  echo FEHLER beim Erzeugen der Assistenten-Grafiken.
  pause
  exit /b 1
)
py -m PyInstaller --noconfirm --clean ^
  --distpath "%~dp0installer\dist" ^
  --workpath "%~dp0installer\build" ^
  "%~dp0installer\CardMaster LS.spec"
if errorlevel 1 (
  echo FEHLER beim Bauen.
  pause
  exit /b 1
)
echo.
echo Fertig: installer\dist\CardMaster LS\CardMaster LS.exe
echo.
echo Setup kompilieren:
echo   "C:\Users\joshu\AppData\Local\Programs\Inno Setup 6\ISCC.exe" "%~dp0installer\cardmaster.iss"
pause
