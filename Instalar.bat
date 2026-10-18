@echo off
cd /d "%~dp0"
echo === Instalando o Bloqueador de Tela ===
py -3.12 --version >nul 2>&1 || (echo Precisa do Python 3.12: https://www.python.org/downloads/ & pause & exit /b 1)
if not exist .venv (
  echo Criando ambiente .venv...
  py -3.12 -m venv .venv || (pause & exit /b 1)
)
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
echo Instalando dependencias...
".venv\Scripts\python.exe" -m pip install -r requirements.txt -q || (pause & exit /b 1)
".venv\Scripts\python.exe" app\instalar.py || (pause & exit /b 1)
echo.
echo Pronto! Abrindo o Painel...
start "" ".venv\Scripts\pythonw.exe" app\painel.py
timeout /t 3 >nul
