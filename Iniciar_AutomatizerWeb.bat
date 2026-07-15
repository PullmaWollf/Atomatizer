@echo off
title Automatizer Web
cd /d "%~dp0"

if not exist venv (
    echo [Automatizer Web] Primeira execucao: preparando ambiente...
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install --upgrade pip >nul
    pip install -r requirements.txt
) else (
    call venv\Scripts\activate.bat
)

echo [Automatizer Web] Abrindo a interface grafica no navegador...
python gui_app.py
pause
