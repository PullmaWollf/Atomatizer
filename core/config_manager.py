"""
config_manager.py
Gerencia as configurações globais (settings.json), os WORKSPACES
(um por cliente/projeto — cada um com suas próprias pastas de macros,
dados, logs, relatórios e cofre de segredos) e o CRUD completo de macros
dentro do workspace ativo.
"""
import json
import os
import shutil
import logging

logger = logging.getLogger("automatizer_web")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_PATH = os.path.join(BASE_DIR, "settings.json")
WORKSPACES_DIR = os.path.join(BASE_DIR, "workspaces")

DEFAULT_SETTINGS = {
    "app_name": "Automatizer Web",
    "active_workspace": "default",
    "browser": {
        "type": "chrome",
        "headless": True,
        "window_size": [1366, 768],
        "profile_path": None,
        "implicit_wait": 10,
    },
    "default_retries": 2,
    "screenshot_on_error": True,
    "gui_port": 5757,
}


# ---------------------------------------------------------------------------
# Configurações globais
# ---------------------------------------------------------------------------
def load_settings() -> dict:
    if not os.path.exists(SETTINGS_PATH):
        save_settings(DEFAULT_SETTINGS)
        return json.loads(json.dumps(DEFAULT_SETTINGS))
    with open(SETTINGS_PATH, encoding="utf-8") as f:
        settings = json.load(f)
    changed = False
    for key, value in DEFAULT_SETTINGS.items():
        if key not in settings:
            settings[key] = value
            changed = True
    if changed:
        save_settings(settings)
    ensure_workspace(settings["active_workspace"])
    return settings


def save_settings(settings: dict):
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
    logger.info("Configurações salvas.")


# ---------------------------------------------------------------------------
# Workspaces (multi-cliente / multi-projeto)
# ---------------------------------------------------------------------------
def list_workspaces():
    os.makedirs(WORKSPACES_DIR, exist_ok=True)
    return sorted(
        d for d in os.listdir(WORKSPACES_DIR)
        if os.path.isdir(os.path.join(WORKSPACES_DIR, d))
    )


def ensure_workspace(name: str):
    """Garante que a estrutura de pastas de um workspace exista."""
    base = os.path.join(WORKSPACES_DIR, name)
    for sub in ("macros", "data", "logs/screenshots", "reports", "vault"):
        os.makedirs(os.path.join(base, sub), exist_ok=True)
    return base


def create_workspace(name: str):
    if name in list_workspaces():
        raise FileExistsError(f"Já existe um workspace chamado '{name}'.")
    ensure_workspace(name)
    logger.info(f"Workspace '{name}' criado.")


def delete_workspace(name: str):
    if name == "default":
        raise ValueError("O workspace 'default' não pode ser excluído.")
    path = os.path.join(WORKSPACES_DIR, name)
    if os.path.exists(path):
        shutil.rmtree(path)
        logger.info(f"Workspace '{name}' excluído.")


def workspace_paths(name: str) -> dict:
    base = ensure_workspace(name)
    return {
        "base": base,
        "macros": os.path.join(base, "macros"),
        "data": os.path.join(base, "data"),
        "logs": os.path.join(base, "logs"),
        "screenshots": os.path.join(base, "logs", "screenshots"),
        "reports": os.path.join(base, "reports"),
        "vault": os.path.join(base, "vault"),
    }


def set_active_workspace(settings: dict, name: str):
    ensure_workspace(name)
    settings["active_workspace"] = name
    save_settings(settings)


# ---------------------------------------------------------------------------
# CRUD de macros (sempre dentro do workspace ativo)
# ---------------------------------------------------------------------------
def list_macros(workspace: str):
    paths = workspace_paths(workspace)
    return sorted(f[:-5] for f in os.listdir(paths["macros"]) if f.endswith(".json"))


def macro_path(workspace: str, name: str) -> str:
    return os.path.join(workspace_paths(workspace)["macros"], f"{name}.json")


def macro_exists(workspace: str, name: str) -> bool:
    return os.path.exists(macro_path(workspace, name))


def load_macro(workspace: str, name: str) -> dict:
    path = macro_path(workspace, name)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Macro '{name}' não existe no workspace '{workspace}'.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_macro(workspace: str, name: str, macro_dict: dict):
    path = macro_path(workspace, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(macro_dict, f, indent=2, ensure_ascii=False)
    logger.info(f"Macro '{name}' salvo em {path}")


def delete_macro(workspace: str, name: str):
    path = macro_path(workspace, name)
    if os.path.exists(path):
        os.remove(path)
        logger.info(f"Macro '{name}' removido do workspace '{workspace}'.")


def rename_macro(workspace: str, old_name: str, new_name: str):
    if not macro_exists(workspace, old_name):
        raise FileNotFoundError(f"Macro '{old_name}' não existe.")
    if macro_exists(workspace, new_name):
        raise FileExistsError(f"Já existe um macro chamado '{new_name}'.")
    d = load_macro(workspace, old_name)
    d["name"] = new_name
    save_macro(workspace, new_name, d)
    delete_macro(workspace, old_name)
    logger.info(f"Macro renomeado de '{old_name}' para '{new_name}'.")


def duplicate_macro(workspace: str, name: str, new_name: str):
    if not macro_exists(workspace, name):
        raise FileNotFoundError(f"Macro '{name}' não existe.")
    if macro_exists(workspace, new_name):
        raise FileExistsError(f"Já existe um macro chamado '{new_name}'.")
    d = load_macro(workspace, name)
    d["name"] = new_name
    save_macro(workspace, new_name, d)
    logger.info(f"Macro '{name}' duplicado como '{new_name}'.")


def export_macro(workspace: str, name: str, destination_path: str):
    src = macro_path(workspace, name)
    if not os.path.exists(src):
        raise FileNotFoundError(f"Macro '{name}' não existe.")
    os.makedirs(os.path.dirname(destination_path) or ".", exist_ok=True)
    shutil.copyfile(src, destination_path)
    logger.info(f"Macro '{name}' exportado para {destination_path}")
    return destination_path


def import_macro(workspace: str, source_path: str, new_name: str = None):
    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Arquivo não encontrado: {source_path}")
    with open(source_path, encoding="utf-8") as f:
        d = json.load(f)
    name = new_name or d.get("name") or os.path.splitext(os.path.basename(source_path))[0]
    if macro_exists(workspace, name):
        raise FileExistsError(f"Já existe um macro chamado '{name}'. Escolha outro nome.")
    d["name"] = name
    save_macro(workspace, name, d)
    logger.info(f"Macro importado de {source_path} como '{name}' no workspace '{workspace}'.")
    return name
