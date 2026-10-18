@echo off
cd /d "%~dp0"
net session >nul 2>&1 || (powershell -Command "Start-Process -Verb RunAs -FilePath \"%~f0\"" & exit /b)
".venv\Scripts\python.exe" bloquear_sites.py
pause
