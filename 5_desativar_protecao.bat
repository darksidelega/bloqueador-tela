@echo off
cd /d "%~dp0"
net session >nul 2>&1 || (powershell -Command "Start-Process -Verb RunAs -FilePath \"%~f0\"" & exit /b)
".venv\Scripts\python.exe" protecao_cli.py desativar
pause
