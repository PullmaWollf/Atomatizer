"""
data_source.py
Carrega arquivos de dados (CSV, JSON ou TXT) localizados na pasta de dados
do workspace ativo, para alimentar os macros com valores variáveis: nomes,
números, códigos, caminhos de anexo etc.

O operador só precisa informar o NOME do arquivo — o caminho completo é
resolvido automaticamente dentro da pasta de dados do workspace.
"""
import csv
import json
import os
import logging

logger = logging.getLogger("automatizer_web")


class DataSource:
    def __init__(self, data_folder: str):
        self.data_folder = data_folder
        os.makedirs(self.data_folder, exist_ok=True)

    def resolve_path(self, filename: str) -> str:
        """Resolve caminho completo dentro da pasta de dados configurada.
        Se já vier um caminho absoluto existente, respeita-o (útil para anexos)."""
        if os.path.isabs(filename) and os.path.exists(filename):
            return filename
        path = os.path.join(self.data_folder, filename)
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Arquivo não encontrado: {path}\n"
                f"Verifique se o arquivo está dentro da pasta '{self.data_folder}'."
            )
        return path

    def load_rows(self, filename: str, fmt: str = None):
        """
        Retorna uma lista de dicionários, um por linha/registro.
        fmt: 'csv' | 'json' | 'txt' (se None, detecta pela extensão do arquivo)
        """
        path = self.resolve_path(filename)
        fmt = (fmt or os.path.splitext(filename)[1].lstrip(".")).lower()

        if fmt == "csv":
            with open(path, newline="", encoding="utf-8-sig") as f:
                return list(csv.DictReader(f))

        if fmt == "json":
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    data = [data]
                return data

        if fmt == "txt":
            with open(path, encoding="utf-8") as f:
                return [{"valor": line.strip()} for line in f if line.strip()]

        raise ValueError(f"Formato de dados não suportado: {fmt}")

    def list_files(self):
        if not os.path.isdir(self.data_folder):
            return []
        return sorted(os.listdir(self.data_folder))
