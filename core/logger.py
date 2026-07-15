"""
logger.py
Configura logging robusto: console colorido + arquivo rotativo em logs/.
Também mascara automaticamente qualquer valor marcado como segredo, para
que credenciais nunca apareçam em texto puro no log ou nos relatórios.
"""
import logging
import os
import re
from logging.handlers import RotatingFileHandler

try:
    from colorama import init as _colorama_init, Fore, Style
    _colorama_init()
    _HAS_COLOR = True
except ImportError:
    _HAS_COLOR = False

APP_NAME = "automatizer_web"

# Nomes de variáveis que, mesmo sem vir do cofre, o operador marcou como
# sensíveis nesta execução (preenchido pelo MacroExecutor em tempo real).
_SECRET_VALUES = set()


def register_secret_value(value: str):
    """Registra um valor em texto puro que nunca deve aparecer em log/relatório
    (ex: senha resolvida do cofre). Chamado pelo executor antes de usá-lo."""
    if value:
        _SECRET_VALUES.add(str(value))


def _mask(text: str) -> str:
    for secret in _SECRET_VALUES:
        if secret and secret in text:
            text = text.replace(secret, "••••••")
    return text


class MaskingFormatter(logging.Formatter):
    def format(self, record):
        original = super().format(record)
        return _mask(original)


class ColorConsoleFormatter(MaskingFormatter):
    COLORS = {
        "DEBUG": "",
        "INFO": "",
        "WARNING": "",
        "ERROR": "",
        "CRITICAL": "",
    }
    if _HAS_COLOR:
        COLORS = {
            "DEBUG": Fore.CYAN,
            "INFO": Fore.GREEN,
            "WARNING": Fore.YELLOW,
            "ERROR": Fore.RED,
            "CRITICAL": Fore.MAGENTA + Style.BRIGHT,
        }

    def format(self, record):
        msg = super().format(record)
        color = self.COLORS.get(record.levelname, "")
        reset = Style.RESET_ALL if _HAS_COLOR else ""
        return f"{color}{msg}{reset}"


def setup_logger(log_folder: str, level=logging.INFO):
    os.makedirs(log_folder, exist_ok=True)
    logger = logging.getLogger(APP_NAME)
    logger.setLevel(level)
    logger.handlers.clear()

    fmt_str = "%(asctime)s [%(levelname)s] %(message)s"
    date_fmt = "%Y-%m-%d %H:%M:%S"

    console = logging.StreamHandler()
    console.setFormatter(ColorConsoleFormatter(fmt_str, date_fmt))
    logger.addHandler(console)

    file_handler = RotatingFileHandler(
        os.path.join(log_folder, "automatizer_web.log"),
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(MaskingFormatter(fmt_str, date_fmt))
    logger.addHandler(file_handler)

    return logger
