@echo off
cd /d "%~dp0"
python graphature_desktop.py
if errorlevel 1 pause
