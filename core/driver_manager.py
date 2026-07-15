"""
driver_manager.py
Responsável por instanciar o WebDriver de forma configurável e robusta.

Selenium 4.6+ resolve o driver binário automaticamente (Selenium Manager),
então não é necessário baixar chromedriver/geckodriver manualmente.

IMPORTANTE sobre "não atrapalhar o input do operador":
headless=True (padrão) faz o navegador rodar SEM JANELA VISÍVEL. Como não
existe janela na tela, ele não pode roubar foco do mouse/teclado do
operador de forma alguma — é a forma correta de deixar a automação
correndo em segundo plano enquanto a pessoa continua usando o computador
normalmente. Use headless=False apenas para depuração visual.
"""
import logging
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.edge.options import Options as EdgeOptions

logger = logging.getLogger("automatizer_web")


def build_driver(browser_config: dict):
    """
    browser_config esperado:
    {
        "type": "chrome" | "firefox" | "edge",
        "headless": true/false,
        "window_size": [1366, 768],
        "profile_path": null ou caminho absoluto de um profile já logado,
        "implicit_wait": 10
    }
    """
    browser_type = browser_config.get("type", "chrome").lower()
    headless = browser_config.get("headless", True)
    window_size = browser_config.get("window_size", [1366, 768])
    profile_path = browser_config.get("profile_path")
    implicit_wait = browser_config.get("implicit_wait", 10)

    logger.info(f"Iniciando driver: browser={browser_type} headless={headless}")

    if browser_type == "chrome":
        options = ChromeOptions()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument(f"--window-size={window_size[0]},{window_size[1]}")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--log-level=3")
        options.add_experimental_option("excludeSwitches", ["enable-logging"])
        if profile_path:
            options.add_argument(f"--user-data-dir={profile_path}")
        driver = webdriver.Chrome(options=options)

    elif browser_type == "firefox":
        options = FirefoxOptions()
        if headless:
            options.add_argument("-headless")
        if profile_path:
            options.profile = profile_path
        driver = webdriver.Firefox(options=options)
        driver.set_window_size(*window_size)

    elif browser_type == "edge":
        options = EdgeOptions()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument(f"--window-size={window_size[0]},{window_size[1]}")
        if profile_path:
            options.add_argument(f"--user-data-dir={profile_path}")
        driver = webdriver.Edge(options=options)

    else:
        raise ValueError(f"Navegador não suportado: {browser_type}")

    driver.implicitly_wait(implicit_wait)
    return driver
