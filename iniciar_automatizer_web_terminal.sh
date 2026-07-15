#!/bin/bash
# Automatizer Web - inicia o menu colorido no terminal
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "[Automatizer Web] Primeira execução: preparando ambiente..."
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip > /dev/null
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

python3 main.py
