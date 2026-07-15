"""
teste_manual_novas_features.py
Exercita de verdade (sem depender só de leitura de código) as novidades:
condicional, laço (repeat_block), seletor alternativo (self-healing),
sub-macro (call_macro) e cofre de segredos — usando um driver falso.
"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.macro import Macro, MacroStep, MacroExecutor
from core.vault import Vault

ok_count = 0
fail_count = 0


def check(desc, condition):
    global ok_count, fail_count
    if condition:
        print(f"  OK  - {desc}")
        ok_count += 1
    else:
        print(f"FALHOU - {desc}")
        fail_count += 1


class FakeElement:
    def __init__(self, name):
        self.name = name
        self.text = f"texto-{name}"
        self.cleared = False
        self.typed = []
        self.clicked = False

    def click(self):
        self.clicked = True

    def clear(self):
        self.cleared = True

    def send_keys(self, *values):
        self.typed.extend(values)

    def get_attribute(self, attr):
        return f"{attr}-de-{self.name}"

    def _record_double_click(self): self.double_clicked = True
    def _record_context_click(self): self.context_clicked = True
    def _record_move_to_element(self): self.hovered = True


class FakeDriver:
    """Simula elementos presentes no 'HTML' via um dicionário locator->elemento."""
    def __init__(self, existing_locators):
        self.existing = existing_locators  # {(by, value): FakeElement}
        self.script_calls = []

    def find_element(self, by, value):
        from selenium.common.exceptions import NoSuchElementException
        key = (by, value)
        if key in self.existing:
            return self.existing[key]
        raise NoSuchElementException(f"{by}={value} não existe")

    def get(self, url):
        pass

    def execute_script(self, script, *args):
        self.script_calls.append(script)
        return "resultado-js"


# ---------------------------------------------------------------------------
# 1) Condicional: if_element_absent pula passo quando elemento existe
# ---------------------------------------------------------------------------
print("\n[1] Testando condicional if_element_absent / if_element_present")
el_aviso = FakeElement("aviso")
el_botao = FakeElement("botao")
driver = FakeDriver({("id", "aviso"): el_aviso, ("id", "botao"): el_botao})

macro = Macro(name="teste_condicional", start_url="")
macro.steps = [
    MacroStep(
        id=1, action="click", locator_type="ID", locator_value="botao",
        condition_type="if_element_absent",
        condition_locator_type="ID", condition_locator_value="aviso",
        timeout=0.3,
    ),
]
executor = MacroExecutor(driver)
executor.run(macro)
check("passo NÃO rodou pois 'aviso' está presente (condição if_element_absent falsa)", el_botao.clicked is False)

# agora sem o aviso -> deve clicar
driver2 = FakeDriver({("id", "botao"): el_botao})
executor2 = MacroExecutor(driver2)
executor2.run(macro)
check("passo RODOU pois 'aviso' não está presente", el_botao.clicked is True)

# ---------------------------------------------------------------------------
# 2) Laço repeat_block por número de vezes
# ---------------------------------------------------------------------------
print("\n[2] Testando repeat_block (N vezes)")
el_item = FakeElement("item")
driver3 = FakeDriver({("id", "item"): el_item})
macro2 = Macro(name="teste_loop", start_url="")
macro2.steps = [
    MacroStep(id=1, action="click", locator_type="ID", locator_value="item", timeout=0.3),
    MacroStep(id=2, action="repeat_block", repeat_from_id=1, repeat_to_id=1, repeat_times=4),
]
click_count = {"n": 0}
orig_click = el_item.click
def counting_click():
    click_count["n"] += 1
el_item.click = counting_click
executor3 = MacroExecutor(driver3)
executor3.run(macro2)
# O passo 1 roda uma vez normalmente (fluxo linear) + 4 vezes dentro do repeat_block = 5
check("repeat_block repetiu o passo 4 vezes além da execução direta (total 5)", click_count["n"] == 5)

# ---------------------------------------------------------------------------
# 3) Seletor alternativo (self-healing)
# ---------------------------------------------------------------------------
print("\n[3] Testando seletor alternativo (fallback)")
el_novo = FakeElement("novo_seletor")
driver4 = FakeDriver({("css selector", ".novo-botao"): el_novo})  # só existe o seletor NOVO
macro3 = Macro(name="teste_fallback", start_url="")
macro3.steps = [
    MacroStep(
        id=1, action="click", locator_type="ID", locator_value="botao-antigo-que-sumiu",
        fallback_locator_type="CSS_SELECTOR", fallback_locator_value=".novo-botao",
        timeout=0.2,
    ),
]
executor4 = MacroExecutor(driver4)
executor4.run(macro3)
check("seletor alternativo foi usado com sucesso quando o principal não existe", el_novo.clicked is True)

# ---------------------------------------------------------------------------
# 4) Cofre de segredos: valor nunca fica no JSON do macro, é resolvido em runtime
# ---------------------------------------------------------------------------
print("\n[4] Testando cofre de segredos (vault)")
with tempfile.TemporaryDirectory() as tmp:
    vault = Vault(tmp)
    vault.unlock("senha-mestra-teste-123")
    vault.set_secret("senha_sistema_x", "S3nh4-Sup3r-Secr3ta")

    el_login = FakeElement("campo_senha")
    driver5 = FakeDriver({("id", "senha"): el_login})
    macro4 = Macro(name="teste_vault", start_url="")
    macro4.steps = [
        MacroStep(
            id=1, action="type", locator_type="ID", locator_value="senha",
            value_source="vault", value="senha_sistema_x", timeout=0.3,
        ),
    ]
    executor5 = MacroExecutor(driver5, vault=vault)
    executor5.run(macro4)
    check("o valor digitado veio do cofre (resolvido em runtime)", "S3nh4-Sup3r-Secr3ta" in el_login.typed)

    # Verifica que o JSON do macro salvo em disco NUNCA contém a senha em texto puro
    macro_json = macro4.to_dict()
    import json
    serializado = json.dumps(macro_json)
    check("a senha NÃO aparece no JSON do macro (só a chave do cofre aparece)", "S3nh4-Sup3r-Secr3ta" not in serializado)
    check("a CHAVE do segredo aparece no JSON (é isso que deveria ser salvo)", "senha_sistema_x" in serializado)

# ---------------------------------------------------------------------------
# 5) Sub-macro (call_macro)
# ---------------------------------------------------------------------------
print("\n[5] Testando sub-macro (call_macro)")
el_login2 = FakeElement("login_btn")
driver6 = FakeDriver({("id", "login_btn"): el_login2})

sub_macro = Macro(name="fazer_login", start_url="")
sub_macro.steps = [MacroStep(id=1, action="click", locator_type="ID", locator_value="login_btn", timeout=0.3)]

macro_principal = Macro(name="fluxo_principal", start_url="")
macro_principal.steps = [MacroStep(id=1, action="call_macro", value="fazer_login")]

def load_macro_fn(name):
    return {"fazer_login": sub_macro}[name]

executor6 = MacroExecutor(driver6, load_macro_fn=load_macro_fn)
executor6.run(macro_principal)
check("sub-macro foi executada e clicou no botão de login", el_login2.clicked is True)

# ---------------------------------------------------------------------------
print(f"\n=== RESULTADO: {ok_count} OK, {fail_count} FALHAS ===")
sys.exit(1 if fail_count else 0)
