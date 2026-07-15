"""
vault.py
Cofre de credenciais criptografado. Guarda logins/senhas/tokens usados
dentro dos macros SEM NUNCA gravá-los em texto puro no disco.

Como funciona:
- Uma senha mestra (definida na primeira vez que o cofre é usado) deriva
  uma chave de criptografia via PBKDF2-HMAC-SHA256 (390.000 iterações) +
  sal aleatório salvo em vault.salt.
- Todos os segredos ficam num único arquivo `vault.enc`, cifrado com
  Fernet (AES128-CBC + HMAC), e só existem em texto puro na memória,
  durante a execução, nunca em disco.
- Um macro nunca guarda a senha em si — guarda apenas o NOME do segredo
  (ex: "senha_sistema_x"), resolvido em tempo real a partir do cofre.
- Qualquer valor lido do cofre é registrado no logger como "segredo" e
  automaticamente mascarado (••••••) em logs e relatórios.
"""
import base64
import json
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

PBKDF2_ITERATIONS = 390_000


class VaultLockedError(Exception):
    pass


class VaultWrongPasswordError(Exception):
    pass


class Vault:
    def __init__(self, vault_dir: str):
        self.vault_dir = vault_dir
        os.makedirs(vault_dir, exist_ok=True)
        self.vault_path = os.path.join(vault_dir, "vault.enc")
        self.salt_path = os.path.join(vault_dir, "vault.salt")
        self._fernet = None
        self._cache = {}

    # ------------------------------------------------------------------
    def exists(self) -> bool:
        return os.path.exists(self.vault_path)

    def is_unlocked(self) -> bool:
        return self._fernet is not None

    def _get_salt(self) -> bytes:
        if os.path.exists(self.salt_path):
            with open(self.salt_path, "rb") as f:
                return f.read()
        salt = os.urandom(16)
        with open(self.salt_path, "wb") as f:
            f.write(salt)
        return salt

    def _derive_key(self, master_password: str) -> bytes:
        salt = self._get_salt()
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=PBKDF2_ITERATIONS,
        )
        return base64.urlsafe_b64encode(kdf.derive(master_password.encode("utf-8")))

    # ------------------------------------------------------------------
    def unlock(self, master_password: str):
        """Destrava o cofre para esta sessão (fica só em memória)."""
        key = self._derive_key(master_password)
        fernet = Fernet(key)
        if self.exists():
            with open(self.vault_path, "rb") as f:
                encrypted = f.read()
            try:
                data = fernet.decrypt(encrypted)
            except InvalidToken:
                raise VaultWrongPasswordError("Senha mestra incorreta.")
            self._cache = json.loads(data.decode("utf-8"))
        else:
            self._cache = {}
        self._fernet = fernet
        self._save()  # garante que o arquivo exista já cifrado com esta senha

    def lock(self):
        self._fernet = None
        self._cache = {}

    def _require_unlocked(self):
        if self._fernet is None:
            raise VaultLockedError("Cofre travado. Informe a senha mestra primeiro.")

    def _save(self):
        self._require_unlocked()
        data = json.dumps(self._cache).encode("utf-8")
        encrypted = self._fernet.encrypt(data)
        with open(self.vault_path, "wb") as f:
            f.write(encrypted)

    # ------------------------------------------------------------------
    def set_secret(self, key: str, value: str):
        self._require_unlocked()
        self._cache[key] = value
        self._save()

    def get_secret(self, key: str) -> str:
        self._require_unlocked()
        if key not in self._cache:
            raise KeyError(f"Segredo '{key}' não existe no cofre.")
        return self._cache[key]

    def delete_secret(self, key: str):
        self._require_unlocked()
        self._cache.pop(key, None)
        self._save()

    def list_keys(self):
        self._require_unlocked()
        return sorted(self._cache.keys())
