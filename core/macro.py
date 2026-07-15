"""
macro.py
Estruturas de dados do Macro (sequência de passos de automação) e o
executor responsável por rodar cada passo no navegador via Selenium.

Além das 22 ações originais (mouse, teclado, formulário, navegação,
alerts, dados, depuração e fluxo), este executor suporta:

- CONDICIONAIS: um passo só roda se uma condição for satisfeita
  (elemento presente/ausente na tela, ou variável capturada igual/
  diferente de um valor). Ex: só clicar em "confirmar" se um elemento
  de aviso NÃO estiver presente.
- LAÇOS (repeat_block): repete um intervalo de passos do próprio macro
  N vezes, ou enquanto um elemento continuar presente na tela (com um
  limite de segurança contra loop infinito).
- SUB-MACROS (call_macro): um passo pode chamar outro macro inteiro
  como se fosse uma função, reaproveitando fluxos comuns (ex: "fazer
  login") dentro de vários macros diferentes.
- SELETOR ALTERNATIVO (self-healing leve): cada passo pode ter um
  segundo localizador de reserva, tentado automaticamente se o
  principal não for encontrado a tempo — reduz quebra quando o HTML
  do sistema-alvo muda ligeiramente.
- COFRE DE SEGREDOS: um valor pode vir do cofre criptografado
  (value_source="vault") em vez de texto fixo, arquivo de dados ou
  variável capturada — nunca fica gravado em texto puro no JSON do
  macro nem aparece em log/relatório.
"""
import re
import os
import time
import logging
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional, List

from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
    NoAlertPresentException,
    NoSuchElementException,
)

from core.locator import to_by
from core.logger import register_secret_value

logger = logging.getLogger("automatizer_web")

# Ações que NÃO precisam de um localizador de elemento
NO_LOCATOR_ACTIONS = {
    "wait",
    "wait_manual",
    "execute_js",
    "switch_to_default_content",
    "switch_to_window",
    "accept_alert",
    "dismiss_alert",
    "type_in_alert",
    "repeat_block",
    "call_macro",
}

# Ações que aceitam origem de valor (fixo / arquivo de dados / variável capturada / cofre)
VALUE_ACTIONS = {"type", "select", "upload_file", "type_in_alert"}

VALUE_SOURCES = ["fixed", "data", "captured", "vault"]

VALID_ACTIONS = [
    "click",
    "double_click",
    "right_click",
    "hover",
    "type",
    "press_key",
    "clear",
    "select",
    "upload_file",
    "scroll_to",
    "extract",
    "execute_js",
    "screenshot",
    "switch_to_frame",
    "switch_to_default_content",
    "switch_to_window",
    "accept_alert",
    "dismiss_alert",
    "type_in_alert",
    "wait",
    "wait_for_element",
    "wait_manual",
    "repeat_block",
    "call_macro",
]

ACTION_LABELS = {
    "click": "Clicar no elemento",
    "double_click": "Duplo clique no elemento",
    "right_click": "Clique com botão direito (menu de contexto)",
    "hover": "Passar o mouse sobre o elemento (hover)",
    "type": "Digitar texto no elemento",
    "press_key": "Pressionar tecla especial (ENTER, TAB, ESC...)",
    "clear": "Limpar o conteúdo do elemento",
    "select": "Selecionar opção em <select>",
    "upload_file": "Enviar arquivo (input file)",
    "scroll_to": "Rolar a página até o elemento",
    "extract": "Extrair texto/atributo e guardar em variável",
    "execute_js": "Executar JavaScript customizado",
    "screenshot": "Tirar print da tela atual",
    "switch_to_frame": "Entrar em um iframe/frame",
    "switch_to_default_content": "Voltar ao conteúdo principal (sair de iframe)",
    "switch_to_window": "Trocar de aba/janela",
    "accept_alert": "Aceitar alerta nativo do navegador (OK)",
    "dismiss_alert": "Cancelar alerta nativo do navegador",
    "type_in_alert": "Digitar texto em um alerta do tipo prompt()",
    "wait": "Aguardar X segundos (tempo fixo)",
    "wait_for_element": "Apenas esperar o elemento aparecer",
    "wait_manual": "Pausar e esperar o operador (ex: resolver CAPTCHA/2FA)",
    "repeat_block": "Repetir um intervalo de passos (laço)",
    "call_macro": "Chamar outro macro (sub-macro)",
}

CONDITION_TYPES = [
    "if_element_present",
    "if_element_absent",
    "if_variable_equals",
    "if_variable_not_equals",
]

CONDITION_LABELS = {
    "if_element_present": "Só executar SE um elemento estiver presente na tela",
    "if_element_absent": "Só executar SE um elemento NÃO estiver presente na tela",
    "if_variable_equals": "Só executar SE uma variável capturada for igual a um valor",
    "if_variable_not_equals": "Só executar SE uma variável capturada for diferente de um valor",
}

MAX_LOOP_ITERATIONS = 500   # trava de segurança contra laço infinito
MAX_SUBMACRO_DEPTH = 5      # trava de segurança contra sub-macro chamando a si mesma

_KEY_ALIASES = {
    "ENTER": Keys.ENTER,
    "TAB": Keys.TAB,
    "ESCAPE": Keys.ESCAPE,
    "ESC": Keys.ESCAPE,
    "BACKSPACE": Keys.BACKSPACE,
    "DELETE": Keys.DELETE,
    "SPACE": Keys.SPACE,
    "ARROW_DOWN": Keys.ARROW_DOWN,
    "ARROW_UP": Keys.ARROW_UP,
    "ARROW_LEFT": Keys.ARROW_LEFT,
    "ARROW_RIGHT": Keys.ARROW_RIGHT,
    "HOME": Keys.HOME,
    "END": Keys.END,
    "PAGE_UP": Keys.PAGE_UP,
    "PAGE_DOWN": Keys.PAGE_DOWN,
}


def resolve_key(name: str):
    key = _KEY_ALIASES.get((name or "").strip().upper())
    if not key:
        raise ValueError(
            f"Tecla '{name}' não reconhecida. Opções: {', '.join(_KEY_ALIASES)}"
        )
    return key


@dataclass
class MacroStep:
    id: int
    action: str
    locator_type: Optional[str] = None
    locator_value: Optional[str] = None
    fallback_locator_type: Optional[str] = None   # seletor alternativo (self-healing)
    fallback_locator_value: Optional[str] = None
    value_source: Optional[str] = None     # "fixed" | "data" | "captured" | "vault"
    value: Optional[str] = None            # texto fixo / coluna / variável / chave do cofre / script JS / tecla / índice
    variable_name: Optional[str] = None    # usado por 'extract' e opcionalmente 'execute_js'
    select_by: Optional[str] = None        # "text" | "value" | "index" (para action=select)
    optional: bool = False                 # se True, elemento não encontrado NÃO interrompe o macro
    wait_before: float = 0
    wait_after: float = 0
    timeout: float = 10

    # condicional
    condition_type: Optional[str] = None
    condition_locator_type: Optional[str] = None
    condition_locator_value: Optional[str] = None
    condition_variable: Optional[str] = None
    condition_value: Optional[str] = None

    # laço (action == "repeat_block")
    repeat_from_id: Optional[int] = None
    repeat_to_id: Optional[int] = None
    repeat_times: Optional[int] = None
    repeat_while_locator_type: Optional[str] = None
    repeat_while_locator_value: Optional[str] = None

    def to_dict(self):
        return asdict(self)


@dataclass
class Macro:
    name: str
    start_url: str = ""
    steps: List[MacroStep] = field(default_factory=list)
    browser_override: Optional[dict] = None   # permite este macro forçar headless=False, por ex.

    def to_dict(self):
        return {
            "name": self.name,
            "start_url": self.start_url,
            "steps": [s.to_dict() for s in self.steps],
            "browser_override": self.browser_override,
        }

    @staticmethod
    def from_dict(d: dict):
        steps = [MacroStep(**s) for s in d.get("steps", [])]
        return Macro(
            name=d["name"],
            start_url=d.get("start_url", ""),
            steps=steps,
            browser_override=d.get("browser_override"),
        )

    def next_id(self) -> int:
        return (max((s.id for s in self.steps), default=0)) + 1

    def move_step(self, step_id: int, direction: int):
        """direction: -1 sobe, +1 desce"""
        idx = next((i for i, s in enumerate(self.steps) if s.id == step_id), None)
        if idx is None:
            return False
        new_idx = idx + direction
        if 0 <= new_idx < len(self.steps):
            self.steps[idx], self.steps[new_idx] = self.steps[new_idx], self.steps[idx]
            return True
        return False


TRANSIENT_EXCEPTIONS = (
    StaleElementReferenceException,
    ElementClickInterceptedException,
    TimeoutException,
)


class MacroExecutor:
    """Executa um Macro em um driver já aberto.

    - data_row: linha de dados (dict) vinda de um CSV/JSON, para value_source="data"
    - data_source: usado para resolver caminhos de upload de arquivo
    - vault: instância de core.vault.Vault já destravada, para value_source="vault"
    - load_macro_fn: função(nome) -> Macro, usada pela ação 'call_macro'
    - default_retries: tentativas extras em falhas transitórias (elemento não
      pronto, clique interceptado, stale element) antes de desistir
    - screenshot_on_error / screenshot_dir: captura de tela automática quando
      um passo falha definitivamente (essencial para depurar execuções
      headless/desatendidas)
    """

    def __init__(
        self,
        driver,
        data_source=None,
        vault=None,
        load_macro_fn=None,
        default_retries: int = 2,
        screenshot_on_error: bool = True,
        screenshot_dir: str = "logs/screenshots",
        _submacro_depth: int = 0,
    ):
        self.driver = driver
        self.data_source = data_source
        self.vault = vault
        self.load_macro_fn = load_macro_fn
        self.default_retries = default_retries
        self.screenshot_on_error = screenshot_on_error
        self.screenshot_dir = screenshot_dir
        self.variables = {}  # variáveis capturadas durante a execução (extract / execute_js)
        self._submacro_depth = _submacro_depth

    # ------------------------------------------------------------------
    # Execução do macro inteiro
    # ------------------------------------------------------------------
    def run(self, macro: Macro, data_row: Optional[dict] = None):
        if macro.start_url:
            logger.info(f"Abrindo URL inicial: {macro.start_url}")
            self.driver.get(macro.start_url)

        steps = macro.steps
        i = 0
        while i < len(steps):
            step = steps[i]

            if not self._condition_met(step):
                logger.info(
                    f"Passo {step.id}: condição não satisfeita ({step.condition_type}); pulando."
                )
                i += 1
                continue

            if step.action == "call_macro":
                self._run_submacro(step, data_row)
                i += 1
                continue

            if step.action == "repeat_block":
                self._run_repeat_block(macro, step, data_row)
                i += 1
                continue

            self._run_step_with_retry(macro, step, data_row)
            i += 1

        return dict(self.variables)

    # ------------------------------------------------------------------
    # Condicionais
    # ------------------------------------------------------------------
    def _element_exists(self, locator_type, locator_value) -> bool:
        try:
            self.driver.find_element(to_by(locator_type), locator_value)
            return True
        except NoSuchElementException:
            return False

    def _condition_met(self, step: MacroStep) -> bool:
        if not step.condition_type:
            return True
        if step.condition_type == "if_variable_equals":
            atual = str(self.variables.get(step.condition_variable, ""))
            return atual == str(step.condition_value)
        if step.condition_type == "if_variable_not_equals":
            atual = str(self.variables.get(step.condition_variable, ""))
            return atual != str(step.condition_value)
        if step.condition_type == "if_element_present":
            return self._element_exists(step.condition_locator_type, step.condition_locator_value)
        if step.condition_type == "if_element_absent":
            return not self._element_exists(step.condition_locator_type, step.condition_locator_value)
        return True

    # ------------------------------------------------------------------
    # Sub-macro (call_macro)
    # ------------------------------------------------------------------
    def _run_submacro(self, step: MacroStep, data_row):
        if self._submacro_depth >= MAX_SUBMACRO_DEPTH:
            raise RecursionError(
                f"Passo {step.id}: limite de {MAX_SUBMACRO_DEPTH} chamadas aninhadas de "
                f"sub-macro atingido (possível chamada circular)."
            )
        if not self.load_macro_fn:
            raise RuntimeError(
                f"Passo {step.id} chama o macro '{step.value}', mas nenhum carregador de "
                f"sub-macro foi configurado neste executor."
            )
        sub_macro = self.load_macro_fn(step.value)
        logger.info(f"Passo {step.id}: chamando sub-macro '{step.value}'...")
        sub_executor = MacroExecutor(
            self.driver,
            data_source=self.data_source,
            vault=self.vault,
            load_macro_fn=self.load_macro_fn,
            default_retries=self.default_retries,
            screenshot_on_error=self.screenshot_on_error,
            screenshot_dir=self.screenshot_dir,
            _submacro_depth=self._submacro_depth + 1,
        )
        sub_executor.variables = self.variables  # compartilha variáveis capturadas
        sub_executor.run(sub_macro, data_row=data_row)
        logger.info(f"Passo {step.id}: sub-macro '{step.value}' concluída.")

    # ------------------------------------------------------------------
    # Laço (repeat_block)
    # ------------------------------------------------------------------
    def _run_repeat_block(self, macro: Macro, step: MacroStep, data_row):
        try:
            start_idx = next(i for i, s in enumerate(macro.steps) if s.id == step.repeat_from_id)
            end_idx = next(i for i, s in enumerate(macro.steps) if s.id == step.repeat_to_id)
        except StopIteration:
            raise ValueError(
                f"Passo {step.id} (repeat_block): 'repeat_from_id'/'repeat_to_id' não "
                f"correspondem a passos existentes neste macro."
            )
        if start_idx > end_idx:
            raise ValueError(f"Passo {step.id}: repeat_from_id deve vir antes de repeat_to_id.")

        bloco = macro.steps[start_idx:end_idx + 1]
        iteracao = 0

        def deve_continuar():
            if step.repeat_times is not None:
                return iteracao < int(step.repeat_times)
            if step.repeat_while_locator_type and step.repeat_while_locator_value:
                return self._element_exists(
                    step.repeat_while_locator_type, step.repeat_while_locator_value
                )
            return False

        logger.info(f"Passo {step.id}: iniciando laço sobre passos {step.repeat_from_id}-{step.repeat_to_id}.")
        while deve_continuar():
            if iteracao >= MAX_LOOP_ITERATIONS:
                logger.warning(
                    f"Passo {step.id}: limite de segurança de {MAX_LOOP_ITERATIONS} "
                    f"iterações atingido; encerrando o laço."
                )
                break
            for sub_step in bloco:
                if not self._condition_met(sub_step):
                    continue
                self._run_step_with_retry(macro, sub_step, data_row)
            iteracao += 1
        logger.info(f"Passo {step.id}: laço concluído após {iteracao} iteração(ões).")

    # ------------------------------------------------------------------
    # Resolução de valores (texto fixo / dados / variável capturada / cofre)
    # ------------------------------------------------------------------
    def _resolve_value(self, step: MacroStep, data_row: Optional[dict]):
        if step.value_source == "data":
            if not data_row or step.value not in data_row:
                raise KeyError(
                    f"Coluna '{step.value}' não encontrada na linha de dados atual."
                )
            raw = data_row[step.value]
        elif step.value_source == "captured":
            if step.value not in self.variables:
                raise KeyError(
                    f"Variável '{step.value}' ainda não foi capturada por nenhum "
                    f"passo 'extract'/'execute_js' anterior neste macro."
                )
            raw = self.variables[step.value]
        elif step.value_source == "vault":
            if not self.vault:
                raise RuntimeError(
                    f"Passo {step.id} usa um valor do cofre ('{step.value}'), mas o "
                    f"cofre não está destravado/configurado nesta execução."
                )
            raw = self.vault.get_secret(step.value)
            register_secret_value(raw)  # nunca aparecerá em log/relatório
        else:
            raw = step.value

        return self._substitute_templates(raw)

    def _substitute_templates(self, text):
        """Permite embutir variáveis capturadas dentro de um texto fixo,
        ex: 'Ticket confirmado: {{ticket_id}}'."""
        if not isinstance(text, str) or "{{" not in text:
            return text

        def repl(m):
            key = m.group(1).strip()
            return str(self.variables.get(key, m.group(0)))

        return re.sub(r"\{\{\s*([\w.]+)\s*\}\}", repl, text)

    # ------------------------------------------------------------------
    # Localização de elementos (com seletor alternativo / self-healing)
    # ------------------------------------------------------------------
    def _condition_for(self, action: str):
        clickable = {"click", "double_click", "right_click", "hover"}
        visible = {"type", "select", "extract"}
        if action in clickable:
            return EC.element_to_be_clickable
        if action in visible:
            return EC.visibility_of_element_located
        return EC.presence_of_element_located  # scroll_to, upload_file, wait_for_element, clear, switch_to_frame

    def _find(self, step: MacroStep):
        condition = self._condition_for(step.action)

        try:
            by = to_by(step.locator_type)
            wait = WebDriverWait(self.driver, step.timeout)
            return wait.until(condition((by, step.locator_value)))
        except TimeoutException:
            if step.fallback_locator_type and step.fallback_locator_value:
                logger.warning(
                    f"Passo {step.id}: seletor principal "
                    f"({step.locator_type}='{step.locator_value}') não encontrado; "
                    f"tentando seletor alternativo..."
                )
                try:
                    fby = to_by(step.fallback_locator_type)
                    fwait = WebDriverWait(self.driver, step.timeout)
                    el = fwait.until(condition((fby, step.fallback_locator_value)))
                    logger.info(f"Passo {step.id}: seletor alternativo funcionou.")
                    return el
                except TimeoutException:
                    pass
            raise TimeoutException(
                f"Passo {step.id}: elemento não encontrado/pronto "
                f"({step.locator_type}='{step.locator_value}') após {step.timeout}s."
            )

    # ------------------------------------------------------------------
    # Execução com retry + screenshot em erro definitivo
    # ------------------------------------------------------------------
    def _run_step_with_retry(self, macro: Macro, step: MacroStep, data_row):
        if step.wait_before:
            time.sleep(step.wait_before)

        logger.info(
            f"Passo {step.id}: {step.action} -> "
            f"{step.locator_type}='{step.locator_value}'"
        )

        max_attempts = 1 if step.action in NO_LOCATOR_ACTIONS else self.default_retries + 1
        last_exc = None

        for attempt in range(1, max_attempts + 1):
            try:
                self._execute(step, data_row)
                if step.wait_after:
                    time.sleep(step.wait_after)
                return
            except TRANSIENT_EXCEPTIONS as e:
                last_exc = e
                if attempt < max_attempts:
                    logger.warning(
                        f"Passo {step.id}: tentativa {attempt} falhou ({e.__class__.__name__}), "
                        f"tentando novamente..."
                    )
                    time.sleep(0.6)
            except NoAlertPresentException as e:
                last_exc = e
                break

        # Falhou definitivamente
        if step.optional:
            logger.warning(
                f"Passo {step.id} é opcional e falhou ({last_exc.__class__.__name__}); "
                f"seguindo para o próximo passo."
            )
            return

        if self.screenshot_on_error:
            self._save_error_screenshot(macro, step)
        raise last_exc

    def _save_error_screenshot(self, macro: Macro, step: MacroStep):
        try:
            os.makedirs(self.screenshot_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(
                self.screenshot_dir, f"erro_{macro.name}_passo{step.id}_{ts}.png"
            )
            self.driver.save_screenshot(path)
            logger.error(f"Screenshot do erro salvo em: {path}")
        except Exception as e:
            logger.error(f"Não foi possível salvar screenshot do erro: {e}")

    # ------------------------------------------------------------------
    # Execução de cada tipo de ação
    # ------------------------------------------------------------------
    def _execute(self, step: MacroStep, data_row: Optional[dict]):
        action = step.action

        if action == "wait":
            time.sleep(float(step.value or 1))

        elif action == "wait_manual":
            mensagem = step.value or "Ação manual necessária."
            print(f"\n>>> PAUSA MANUAL: {mensagem}")
            input(">>> Pressione ENTER aqui no terminal para o macro continuar...")

        elif action == "wait_for_element":
            self._find(step)

        elif action == "click":
            self._find(step).click()

        elif action == "double_click":
            ActionChains(self.driver).double_click(self._find(step)).perform()

        elif action == "right_click":
            ActionChains(self.driver).context_click(self._find(step)).perform()

        elif action == "hover":
            ActionChains(self.driver).move_to_element(self._find(step)).perform()

        elif action == "clear":
            self._find(step).clear()

        elif action == "type":
            el = self._find(step)
            el.clear()
            el.send_keys(self._resolve_value(step, data_row))

        elif action == "press_key":
            key = resolve_key(step.value)
            if step.locator_type and step.locator_value:
                self._find(step).send_keys(key)
            else:
                self.driver.switch_to.active_element.send_keys(key)

        elif action == "select":
            sel = Select(self._find(step))
            value = self._resolve_value(step, data_row)
            by_kind = step.select_by or "text"
            if by_kind == "text":
                sel.select_by_visible_text(value)
            elif by_kind == "value":
                sel.select_by_value(value)
            elif by_kind == "index":
                sel.select_by_index(int(value))

        elif action == "upload_file":
            el = self._find(step)
            value = self._resolve_value(step, data_row)
            if self.data_source:
                value = self.data_source.resolve_path(value)
            el.send_keys(value)

        elif action == "scroll_to":
            el = self._find(step)
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", el
            )

        elif action == "extract":
            el = self._find(step)
            captured = el.get_attribute(step.value) if step.value else el.text
            if not step.variable_name:
                raise ValueError(f"Passo {step.id} (extract) precisa de 'variable_name'.")
            self.variables[step.variable_name] = captured
            logger.info(f"Variável capturada: {step.variable_name} = {captured!r}")

        elif action == "execute_js":
            result = self.driver.execute_script(step.value)
            if step.variable_name:
                self.variables[step.variable_name] = result
                logger.info(f"Variável capturada via JS: {step.variable_name} = {result!r}")

        elif action == "screenshot":
            os.makedirs(self.screenshot_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = step.value or f"passo{step.id}_{ts}.png"
            path = os.path.join(self.screenshot_dir, filename)
            self.driver.save_screenshot(path)
            logger.info(f"Screenshot salvo em: {path}")

        elif action == "switch_to_frame":
            el = self._find(step)
            self.driver.switch_to.frame(el)

        elif action == "switch_to_default_content":
            self.driver.switch_to.default_content()

        elif action == "switch_to_window":
            index = int(step.value or 0)
            handles = self.driver.window_handles
            if index >= len(handles):
                raise NoSuchElementException(
                    f"Passo {step.id}: janela/aba de índice {index} não existe "
                    f"(existem {len(handles)} aberta(s))."
                )
            self.driver.switch_to.window(handles[index])

        elif action == "accept_alert":
            self.driver.switch_to.alert.accept()

        elif action == "dismiss_alert":
            self.driver.switch_to.alert.dismiss()

        elif action == "type_in_alert":
            value = self._resolve_value(step, data_row)
            self.driver.switch_to.alert.send_keys(value)

        else:
            raise ValueError(f"Ação desconhecida: {action}")
