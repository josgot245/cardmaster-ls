@echo off
rem CardMaster LS (Spesenzettel aus der Fahrerkarte) starten
cd /d "%~dp0"
py spesenzettel_gui.py
if errorlevel 1 pause
