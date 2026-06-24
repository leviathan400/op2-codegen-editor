@echo off
REM Startet den OP2 Mission Editor. Doppelklick genuegt.
cd /d "%~dp0"
python main.py
if errorlevel 1 pause
