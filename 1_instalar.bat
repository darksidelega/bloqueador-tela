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
".venv\Scripts\python.exe" baixar_modelos.py || (pause & exit /b 1)
".venv\Scripts\python.exe" -c "from bloqueador import config; config.carregar()"
echo.
echo Pronto! Ajustes ficam em config.json.
echo  - 2_iniciar.bat           : inicia o bloqueador
echo  - 4_ativar_protecao.bat   : senha + iniciar com o Windows + bloquear sites
echo.
pause
