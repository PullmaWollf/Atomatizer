"""
locator.py
Mapeamento completo dos tipos de localizadores suportados pelo Selenium.
Qualquer elemento do HTML pode ser encontrado por um destes 8 métodos.
"""
from selenium.webdriver.common.by import By
from enum import Enum


class LocatorType(str, Enum):
    ID = "ID"
    NAME = "NAME"
    CLASS_NAME = "CLASS_NAME"
    TAG_NAME = "TAG_NAME"
    LINK_TEXT = "LINK_TEXT"
    PARTIAL_LINK_TEXT = "PARTIAL_LINK_TEXT"
    CSS_SELECTOR = "CSS_SELECTOR"
    XPATH = "XPATH"

    @classmethod
    def menu(cls):
        """Lista ordenada para exibição em menu numerado no terminal."""
        return list(cls)


_BY_MAP = {
    LocatorType.ID: By.ID,
    LocatorType.NAME: By.NAME,
    LocatorType.CLASS_NAME: By.CLASS_NAME,
    LocatorType.TAG_NAME: By.TAG_NAME,
    LocatorType.LINK_TEXT: By.LINK_TEXT,
    LocatorType.PARTIAL_LINK_TEXT: By.PARTIAL_LINK_TEXT,
    LocatorType.CSS_SELECTOR: By.CSS_SELECTOR,
    LocatorType.XPATH: By.XPATH,
}


def to_by(locator_type: str):
    """Converte a string salva no JSON do macro para a constante By do Selenium."""
    lt = LocatorType(locator_type)
    return _BY_MAP[lt]
