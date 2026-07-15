"""
rodar_todos_os_testes.py
Roda toda a suíte de testes do Automatizer Web sem depender de pytest
(usa só a biblioteca padrão + as dependências do requirements.txt).

Uso:
    python tests/rodar_todos_os_testes.py
"""
import subprocess
import sys
import os

TESTES = [
    "teste_workspaces_e_agendador.py",
    "teste_manual_novas_features.py",
]

base = os.path.dirname(os.path.abspath(__file__))
falhou = False

for nome in TESTES:
    print(f"\n{'=' * 70}\nRODANDO: {nome}\n{'=' * 70}")
    r = subprocess.run([sys.executable, os.path.join(base, nome)])
    if r.returncode != 0:
        falhou = True

print("\n" + ("❌ ALGUM TESTE FALHOU" if falhou else "✅ TODOS OS TESTES PASSARAM"))
sys.exit(1 if falhou else 0)
