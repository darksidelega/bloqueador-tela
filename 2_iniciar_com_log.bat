@echo off
rem Abre com console para ver o DEBUG (classe + pontuacao). Log tambem fica em logs\bloqueador.log
cd /d "%~dp0"
".venv\Scripts\python.exe" bloqueador_tela.py
pause
