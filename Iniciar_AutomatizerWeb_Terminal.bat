@echo off
title Automatizer Web - Terminal
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

python main.py
pause
