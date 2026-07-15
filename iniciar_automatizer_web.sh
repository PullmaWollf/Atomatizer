#!/bin/bash
# Automatizer Web - inicia a interface gráfica (dashboard no navegador)
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

echo "[Automatizer Web] Abrindo a interface gráfica no navegador..."
python3 gui_app.py
