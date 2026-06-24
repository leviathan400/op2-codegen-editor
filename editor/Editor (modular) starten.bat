@echo off
REM Startet die modulare Editor-Version (Paket app/). Doppelklick genuegt.
cd /d "%~dp0"
python -m app
if errorlevel 1 pause
