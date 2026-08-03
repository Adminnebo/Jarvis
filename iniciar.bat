@echo off
title Jarvis
cd /d "%~dp0"

set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=python

if not exist ".venv" (
  echo Preparando el entorno por primera vez...
  "%PY%" -m venv .venv
  call .venv\Scripts\activate.bat
  python -m pip install --upgrade pip --quiet
  python -m pip install -r requirements.txt --quiet
) else (
  call .venv\Scripts\activate.bat
)

if not exist ".env" (
  copy .env.example .env >nul
  echo.
  echo  ATENCION: se creo el archivo .env
  echo  Abrelo y pon tu clave de OpenAI antes de hablar con Jarvis.
  echo.
)

echo Jarvis escuchando en http://127.0.0.1:8123
start "" http://127.0.0.1:8123
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8123
pause
