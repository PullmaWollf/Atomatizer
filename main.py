"""
main.py
=========================================================
AUTOMATIZER WEB — Menu Interativo (White Label)
=========================================================
Ferramenta genérica de automação de navegador via Selenium. O mesmo
código serve para QUALQUER processo repetitivo em qualquer sistema web.
O que muda entre uma automação e outra é apenas o "macro" (arquivo de
configuração), criado interativamente por este menu — ou pela interface
gráfica (opção 9).

Menu principal:
  1. Executar Macro
  2. Marcar Coordenadas      -> cria/edita/reordena os passos de um macro
  3. Limpar Coordenadas      -> remove passos de um macro existente
  4. Gerenciar Macros        -> duplicar / exportar / importar / renomear
  5. Cofre de Segredos       -> credenciais criptografadas (login/senha)
  6. Agendamentos            -> rodar macros automaticamente em horário fixo
  7. Workspaces              -> um espaço isolado por cliente/projeto
  8. Configurações
  9. Abrir Interface Gráfica (navegador)
  10. Sair
"""
import csv
import getpass
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from core import config_manager as cfg
from core.logger import setup_logger
from core.locator import LocatorType
from core.macro import (
    Macro,
    MacroStep,
    MacroExecutor,
    VALID_ACTIONS,
    ACTION_LABELS,
    NO_LOCATOR_ACTIONS,
    VALUE_ACTIONS,
    CONDITION_TYPES,
    CONDITION_LABELS,
    _KEY_ALIASES,
)
from core.driver_manager import build_driver
from core.data_source import DataSource
from core.vault import Vault, VaultWrongPasswordError
from core.scheduler import SchedulerManager, WEEKDAYS, WEEKDAY_LABELS_PT

console = Console()

SETTINGS = cfg.load_settings()
APP_NAME = SETTINGS.get("app_name", "Automatizer Web")

WORKSPACE = SETTINGS["active_workspace"]
PATHS = cfg.workspace_paths(WORKSPACE)
logger = setup_logger(PATHS["logs"])

RUNNING_THREADS = {}   # nome_macro -> threading.Thread
VAULT = Vault(PATHS["vault"])
SCHEDULER = None  # instanciado em main()


# ---------------------------------------------------------------------------
# Helpers de input / apresentação (coloridos via rich)
# ---------------------------------------------------------------------------
def clear():
    os.system("cls" if os.name == "nt" else "clear")


def banner():
    ativos = list(RUNNING_THREADS.keys())
    linhas = f"[bold]Workspace ativo:[/bold] {WORKSPACE}"
    if ativos:
        linhas += f"\n[yellow]Execuções ativas em segundo plano:[/yellow] {', '.join(ativos)}"
    console.print(Panel.fit(
        f"[bold cyan]{APP_NAME}[/bold cyan]\n{linhas}",
        border_style="cyan",
    ))


def pause():
    console.input("\n[dim]Pressione ENTER para continuar...[/dim]")


def ask_choice(prompt, options, allow_cancel=True):
    while True:
        console.print(f"\n[bold]{prompt}[/bold]")
        for i, opt in enumerate(options, 1):
            console.print(f"  [cyan]{i}.[/cyan] {opt}")
        if allow_cancel:
            console.print("  [red]0.[/red] Cancelar")
        raw = console.input("Escolha: ").strip()
        if allow_cancel and raw == "0":
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        console.print("[red]Opção inválida.[/red]")


def ask_text(prompt, default=None, allow_empty=False):
    suffix = f" [dim][{default}][/dim]" if default is not None else ""
    while True:
        raw = console.input(f"{prompt}{suffix}: ").strip()
        if not raw and default is not None:
            return default
        if not raw and allow_empty:
            return ""
        if raw:
            return raw
        console.print("[red]Valor obrigatório.[/red]")


def ask_float(prompt, default=0.0):
    raw = console.input(f"{prompt} [dim][{default}][/dim]: ").strip()
    if not raw:
        return default
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        console.print("[red]Valor inválido, usando padrão.[/red]")
        return default


def ask_yes_no(prompt, default=True):
    d = "S" if default else "N"
    raw = console.input(f"{prompt} (s/n) [dim][{d}][/dim]: ").strip().lower()
    if not raw:
        return default
    return raw.startswith("s")


def executor_kwargs():
    def _load_macro_fn(name):
        return Macro.from_dict(cfg.load_macro(WORKSPACE, name))

    return dict(
        vault=VAULT if VAULT.is_unlocked() else None,
        load_macro_fn=_load_macro_fn,
        default_retries=int(SETTINGS.get("default_retries", 2)),
        screenshot_on_error=SETTINGS.get("screenshot_on_error", True),
        screenshot_dir=PATHS["screenshots"],
    )


# ---------------------------------------------------------------------------
# Relatório de execução em lote
# ---------------------------------------------------------------------------
def _gravar_relatorio(macro_name, resultados):
    os.makedirs(PATHS["reports"], exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(PATHS["reports"], f"{macro_name}_{ts}.csv")
    campos = ["linha", "status", "erro", "variaveis_capturadas"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        for r in resultados:
            writer.writerow(r)
    return path


# ---------------------------------------------------------------------------
# 1. Executar Macro
# ---------------------------------------------------------------------------
def _executar_macro_worker(macro: Macro, data_rows, headless_override=None):
    driver = None
    try:
        browser_cfg = dict(SETTINGS["browser"])
        if macro.browser_override:
            browser_cfg.update(macro.browser_override)
        if headless_override is not None:
            browser_cfg["headless"] = headless_override

        driver = build_driver(browser_cfg)
        data_source = DataSource(PATHS["data"])
        executor = MacroExecutor(driver, data_source, **executor_kwargs())

        if data_rows:
            resultados = []
            for i, row in enumerate(data_rows, 1):
                logger.info(f"[{macro.name}] Registro {i}/{len(data_rows)}: {row}")
                try:
                    variaveis = executor.run(macro, data_row=row)
                    resultados.append(
                        {"linha": i, "status": "OK", "erro": "", "variaveis_capturadas": variaveis}
                    )
                except Exception as e:
                    logger.error(f"[{macro.name}] Registro {i} FALHOU: {e}")
                    resultados.append(
                        {"linha": i, "status": "ERRO", "erro": str(e), "variaveis_capturadas": ""}
                    )
            path = _gravar_relatorio(macro.name, resultados)
            ok = sum(1 for r in resultados if r["status"] == "OK")
            logger.info(
                f"[{macro.name}] Lote concluído: {ok}/{len(resultados)} OK. "
                f"Relatório: {path}"
            )
        else:
            executor.run(macro)
            logger.info(f"[{macro.name}] Execução finalizada com sucesso.")

    except Exception as e:
        logger.error(f"[{macro.name}] ERRO durante a execução: {e}")
    finally:
        if driver:
            driver.quit()
        RUNNING_THREADS.pop(macro.name, None)


def _rodar_macro_por_nome(macro_name: str, data_file: str = None):
    """Usado pelo agendador: roda um macro pelo nome, opcionalmente com um
    arquivo de dados em lote, sempre em segundo plano headless."""
    macro = Macro.from_dict(cfg.load_macro(WORKSPACE, macro_name))
    data_rows = None
    if data_file:
        data_source = DataSource(PATHS["data"])
        data_rows = data_source.load_rows(data_file)
    _executar_macro_worker(macro, data_rows, headless_override=None)


def menu_executar_macro():
    clear()
    banner()
    macros = cfg.list_macros(WORKSPACE)
    if not macros:
        console.print("[yellow]Nenhum macro cadastrado ainda. Use 'Marcar Coordenadas' primeiro.[/yellow]")
        pause()
        return

    idx = ask_choice("=== EXECUTAR MACRO ===\nEscolha o macro:", macros)
    if idx is None:
        return
    name = macros[idx]
    macro = Macro.from_dict(cfg.load_macro(WORKSPACE, name))

    if not macro.steps:
        console.print("[yellow]Este macro não tem passos configurados.[/yellow]")
        pause()
        return

    usar_dados = ask_yes_no(
        "\nEsta execução deve repetir o macro para VÁRIOS registros de um arquivo de dados?",
        default=False,
    )
    data_rows = None
    if usar_dados:
        data_source = DataSource(PATHS["data"])
        arquivos = data_source.list_files()
        if not arquivos:
            console.print(f"[yellow]Nenhum arquivo encontrado em '{PATHS['data']}'.[/yellow]")
            pause()
            return
        idx2 = ask_choice("Escolha o arquivo de dados:", arquivos)
        if idx2 is None:
            return
        data_rows = data_source.load_rows(arquivos[idx2])
        console.print(f"[green]{len(data_rows)} registro(s) carregado(s).[/green]")

    ver_execucao = ask_yes_no(
        "\nQuer VER o navegador rodando agora (janela visível, só para esta execução)?",
        default=False,
    )
    headless_override = False if ver_execucao else None

    modo_daemon = ask_yes_no(
        "\nExecutar em segundo plano (thread daemon), liberando o menu imediatamente?",
        default=not ver_execucao,
    )

    if macro.name in RUNNING_THREADS:
        console.print(f"[red]O macro '{macro.name}' já está em execução.[/red]")
        pause()
        return

    if modo_daemon:
        t = threading.Thread(
            target=_executar_macro_worker,
            args=(macro, data_rows, headless_override),
            daemon=True,
        )
        RUNNING_THREADS[macro.name] = t
        t.start()
        console.print(
            f"\n[green]Macro '{macro.name}' iniciado em segundo plano.[/green] "
            f"Acompanhe em {os.path.join(PATHS['logs'], 'automatizer_web.log')}."
        )
    else:
        console.print("\n[cyan]Executando (modo bloqueante)...[/cyan]")
        _executar_macro_worker(macro, data_rows, headless_override)
    pause()


# ---------------------------------------------------------------------------
# 2. Marcar Coordenadas (criar/editar/reordenar macro)
# ---------------------------------------------------------------------------
def _escolher_ou_criar_macro():
    macros = cfg.list_macros(WORKSPACE)
    opcoes = ["Criar novo macro"] + macros
    idx = ask_choice("Escolha um macro para editar ou crie um novo:", opcoes)
    if idx is None:
        return None
    if idx == 0:
        nome = ask_text("Nome do novo macro (sem espaços/acentos)")
        url = ask_text("URL inicial que o navegador deve abrir (ex: https://sistema.com/login)")
        macro = Macro(name=nome, start_url=url)
        cfg.save_macro(WORKSPACE, nome, macro.to_dict())
        return macro
    nome = macros[idx - 1]
    return Macro.from_dict(cfg.load_macro(WORKSPACE, nome))


def _capturar_localizador(prompt_titulo, default_type=None, default_value=None):
    tipos = [t.value for t in LocatorType.menu()]
    default_idx = tipos.index(default_type) if default_type in tipos else None
    idx_tipo = ask_choice(prompt_titulo, tipos)
    if idx_tipo is None:
        return None, None
    locator_type = tipos[idx_tipo]
    if locator_type == "XPATH":
        exemplo = "//button[@id='salvar']"
    elif locator_type == "CSS_SELECTOR":
        exemplo = "#salvar, .btn-primary"
    else:
        exemplo = "salvar"
    locator_value = ask_text(f"Valor do localizador (ex: {exemplo})", default=default_value)
    return locator_type, locator_value


def _capturar_dados_passo(existing: MacroStep = None):
    """Fluxo de perguntas compartilhado entre 'adicionar passo' e 'editar
    passo'. Retorna um dict com os campos coletados (sem o 'id')."""
    acoes = list(VALID_ACTIONS)
    console.print(
        f"\n[dim](Passo atual: {ACTION_LABELS.get(existing.action)})[/dim]" if existing else ""
    )
    idx_acao = ask_choice(
        "Ação a executar:", [ACTION_LABELS.get(a, a) for a in acoes]
    )
    if idx_acao is None:
        return None
    action = acoes[idx_acao]

    # ---- Ações especiais: sub-macro e laço ----------------------------
    if action == "call_macro":
        outros = [m for m in cfg.list_macros(WORKSPACE) if not existing or m != existing.value]
        if not outros:
            console.print("[yellow]Não há outro macro para chamar como sub-macro.[/yellow]")
            return None
        idx_m = ask_choice("Qual macro chamar como sub-macro?", outros)
        if idx_m is None:
            return None
        return dict(action=action, value=outros[idx_m])

    if action == "repeat_block":
        de = ask_text("Repetir A PARTIR do número do passo (id)")
        ate = ask_text("Repetir ATÉ o número do passo (id)")
        modo = ask_choice("Repetir quantas vezes?", ["Número fixo de vezes", "Enquanto um elemento estiver presente na tela"])
        if modo is None:
            return None
        repeat_times = None
        repeat_while_locator_type = None
        repeat_while_locator_value = None
        if modo == 0:
            repeat_times = int(ask_float("Quantas vezes repetir?", 1))
        else:
            repeat_while_locator_type, repeat_while_locator_value = _capturar_localizador(
                "Tipo de localizador do elemento que indica 'continuar repetindo':"
            )
        return dict(
            action=action,
            repeat_from_id=int(de) if de.isdigit() else None,
            repeat_to_id=int(ate) if ate.isdigit() else None,
            repeat_times=repeat_times,
            repeat_while_locator_type=repeat_while_locator_type,
            repeat_while_locator_value=repeat_while_locator_value,
        )

    # ---- Localizador principal + alternativo (self-healing) -----------
    locator_type = None
    locator_value = None
    fallback_locator_type = None
    fallback_locator_value = None
    if action not in NO_LOCATOR_ACTIONS:
        precisa_locator = True
        if action == "press_key":
            precisa_locator = ask_yes_no(
                "Enviar a tecla para um elemento específico? "
                "(não = envia para o elemento em foco no momento)",
                default=bool(existing and existing.locator_type),
            )
        if precisa_locator:
            locator_type, locator_value = _capturar_localizador(
                "Tipo de localizador do elemento HTML:",
                existing.locator_type if existing else None,
                existing.locator_value if existing else None,
            )
            usar_fallback = ask_yes_no(
                "Definir um SELETOR ALTERNATIVO (usado automaticamente se o principal "
                "não for encontrado — útil se o HTML do sistema mudar)?",
                default=bool(existing and existing.fallback_locator_type) if existing else False,
            )
            if usar_fallback:
                fallback_locator_type, fallback_locator_value = _capturar_localizador(
                    "Tipo do seletor ALTERNATIVO:",
                    existing.fallback_locator_type if existing else None,
                    existing.fallback_locator_value if existing else None,
                )

    value_source = None
    value = None
    variable_name = None
    select_by = None

    if action in VALUE_ACTIONS:
        origem_opcoes = [
            "Texto fixo (digitado agora)",
            "Coluna de um arquivo de dados (data/)",
            "Variável capturada por um passo 'extract'/'execute_js' anterior",
            "Cofre de segredos (login/senha protegidos)",
        ]
        origem = ask_choice("De onde vem o valor?", origem_opcoes)
        if origem is None:
            return None
        value_source = {0: "fixed", 1: "data", 2: "captured", 3: "vault"}[origem]
        if origem == 0:
            if action == "upload_file":
                value = ask_text(
                    "Nome do arquivo a enviar (deve estar dentro da pasta de dados). "
                    "Dica: pode usar {{variavel}} para montar caminhos dinâmicos"
                )
            else:
                value = ask_text(
                    "Texto/valor fixo. Dica: pode usar {{variavel}} para incluir "
                    "valores capturados anteriormente"
                )
        elif origem == 1:
            value = ask_text("Nome da COLUNA no arquivo de dados (cabeçalho do CSV/JSON)")
        elif origem == 2:
            value = ask_text("Nome da variável já capturada neste macro")
        else:
            if not VAULT.is_unlocked():
                console.print(
                    "[yellow]O cofre está travado. Vá em 'Cofre de Segredos' no menu "
                    "principal para destravar e cadastrar a credencial antes de usá-la aqui.[/yellow]"
                )
            chaves = VAULT.list_keys() if VAULT.is_unlocked() else []
            if chaves:
                idx_chave = ask_choice("Qual segredo do cofre usar?", chaves)
                value = chaves[idx_chave] if idx_chave is not None else ask_text("Nome (chave) do segredo no cofre")
            else:
                value = ask_text("Nome (chave) do segredo no cofre")

        if action == "select":
            idx_sb = ask_choice(
                "Selecionar a opção do <select> por:",
                ["Texto visível", "Atributo value", "Índice"],
            )
            select_by = {0: "text", 1: "value", 2: "index"}.get(idx_sb, "text")

    elif action == "wait":
        value = str(ask_float("Quantos segundos aguardar?", 1.0))

    elif action == "wait_manual":
        value = ask_text(
            "Mensagem a exibir para o operador (ex: 'Resolva o CAPTCHA e pressione ENTER')",
            default="Ação manual necessária.",
        )

    elif action == "press_key":
        nomes = list(_KEY_ALIASES.keys())
        idx_key = ask_choice("Qual tecla enviar?", nomes)
        if idx_key is None:
            return None
        value = nomes[idx_key]

    elif action == "extract":
        quer_atributo = ask_yes_no(
            "Extrair um ATRIBUTO específico do elemento? (não = extrai o texto visível)",
            default=False,
        )
        value = ask_text("Nome do atributo (ex: value, href, data-id)") if quer_atributo else None
        variable_name = ask_text("Nome da variável para guardar este valor capturado")

    elif action == "execute_js":
        value = ask_text(
            "Código JavaScript a executar (use 'return ...' se quiser capturar um valor)"
        )
        quer_var = ask_yes_no("Guardar o retorno deste script em uma variável?", default=False)
        variable_name = ask_text("Nome da variável") if quer_var else None

    elif action == "screenshot":
        value = ask_text(
            "Nome do arquivo do print (opcional, ENTER para gerar automático)",
            allow_empty=True,
        ) or None

    elif action == "switch_to_window":
        value = ask_text("Índice da janela/aba (0 = primeira aberta, 1 = segunda...)", default="0")

    optional = False
    if action not in NO_LOCATOR_ACTIONS:
        optional = ask_yes_no(
            "Este passo é OPCIONAL? (se o elemento não existir, pula sem falhar o macro)",
            default=existing.optional if existing else False,
        )

    # ---- Condicional ----------------------------------------------------
    condition_type = None
    condition_locator_type = None
    condition_locator_value = None
    condition_variable = None
    condition_value = None
    usar_condicao = ask_yes_no(
        "Este passo deve ser CONDICIONAL (só roda se uma condição for satisfeita)?",
        default=bool(existing and existing.condition_type) if existing else False,
    )
    if usar_condicao:
        idx_c = ask_choice("Tipo de condição:", [CONDITION_LABELS[c] for c in CONDITION_TYPES])
        if idx_c is not None:
            condition_type = CONDITION_TYPES[idx_c]
            if condition_type in ("if_element_present", "if_element_absent"):
                condition_locator_type, condition_locator_value = _capturar_localizador(
                    "Localizador do elemento usado na condição:"
                )
            else:
                condition_variable = ask_text("Nome da variável a comparar")
                condition_value = ask_text("Valor de comparação")

    wait_before = ask_float("Aguardar quantos segundos ANTES deste passo?", existing.wait_before if existing else 0)
    wait_after = ask_float("Aguardar quantos segundos DEPOIS deste passo?", existing.wait_after if existing else 0)
    timeout = ask_float(
        "Timeout (segundos) para localizar o elemento?", existing.timeout if existing else 10
    )

    return dict(
        action=action,
        locator_type=locator_type,
        locator_value=locator_value,
        fallback_locator_type=fallback_locator_type,
        fallback_locator_value=fallback_locator_value,
        value_source=value_source,
        value=value,
        variable_name=variable_name,
        select_by=select_by,
        optional=optional,
        wait_before=wait_before,
        wait_after=wait_after,
        timeout=timeout,
        condition_type=condition_type,
        condition_locator_type=condition_locator_type,
        condition_locator_value=condition_locator_value,
        condition_variable=condition_variable,
        condition_value=condition_value,
    )


def _adicionar_passo(macro: Macro):
    console.print(f"\n--- Novo passo para o macro '{macro.name}' ---")
    dados = _capturar_dados_passo()
    if dados is None:
        return
    step = MacroStep(id=macro.next_id(), **dados)
    macro.steps.append(step)
    cfg.save_macro(WORKSPACE, macro.name, macro.to_dict())
    console.print(f"[green]Passo #{step.id} adicionado e salvo.[/green]")


def _editar_passo(macro: Macro):
    if not macro.steps:
        console.print("[yellow]Nenhum passo para editar.[/yellow]")
        return
    num = ask_text("Número do passo a editar")
    if not num.isdigit():
        return
    step_id = int(num)
    step = next((s for s in macro.steps if s.id == step_id), None)
    if not step:
        console.print("[red]Passo não encontrado.[/red]")
        return
    console.print(f"\n--- Editando passo #{step_id} ---")
    dados = _capturar_dados_passo(existing=step)
    if dados is None:
        return
    for k, v in dados.items():
        setattr(step, k, v)
    cfg.save_macro(WORKSPACE, macro.name, macro.to_dict())
    console.print(f"[green]Passo #{step_id} atualizado.[/green]")


def _reordenar_passos(macro: Macro):
    if len(macro.steps) < 2:
        console.print("[yellow]É preciso ao menos 2 passos para reordenar.[/yellow]")
        return
    num = ask_text("Número do passo a mover")
    if not num.isdigit():
        return
    direcao = ask_choice("Mover para:", ["Cima", "Baixo"])
    if direcao is None:
        return
    ok = macro.move_step(int(num), -1 if direcao == 0 else 1)
    if ok:
        cfg.save_macro(WORKSPACE, macro.name, macro.to_dict())
        console.print("[green]Passo reordenado.[/green]")
    else:
        console.print("[red]Não foi possível mover (já está na ponta ou passo inexistente).[/red]")


def _tabela_passos(macro: Macro):
    table = Table(title=f"Passos de '{macro.name}'")
    table.add_column("#", style="cyan")
    table.add_column("Ação")
    table.add_column("Localizador")
    table.add_column("Extras")
    for s in macro.steps:
        extras = []
        if s.optional:
            extras.append("opcional")
        if s.condition_type:
            extras.append(f"condição:{s.condition_type}")
        if s.fallback_locator_type:
            extras.append("seletor alternativo")
        table.add_row(
            str(s.id),
            ACTION_LABELS.get(s.action, s.action),
            f"{s.locator_type or '-'}='{s.locator_value or '-'}'",
            ", ".join(extras) or "-",
        )
    console.print(table)


def menu_marcar_coordenadas():
    clear()
    banner()
    console.print("[bold]=== MARCAR COORDENADAS (elementos do HTML) ===[/bold]")
    macro = _escolher_ou_criar_macro()
    if macro is None:
        return

    while True:
        clear()
        banner()
        console.print(f"Macro atual: [bold]{macro.name}[/bold]  |  URL inicial: {macro.start_url}")
        _tabela_passos(macro)

        idx = ask_choice(
            "\nO que deseja fazer?",
            [
                "Adicionar novo passo (marcar novo elemento)",
                "Editar um passo existente",
                "Reordenar passos (mover para cima/baixo)",
                "Alterar URL inicial do macro",
                "Voltar ao menu principal",
            ],
        )
        if idx is None or idx == 4:
            return
        if idx == 0:
            _adicionar_passo(macro)
            pause()
        elif idx == 1:
            _editar_passo(macro)
            pause()
        elif idx == 2:
            _reordenar_passos(macro)
            pause()
        elif idx == 3:
            macro.start_url = ask_text("Nova URL inicial", default=macro.start_url)
            cfg.save_macro(WORKSPACE, macro.name, macro.to_dict())


# ---------------------------------------------------------------------------
# 3. Limpar Coordenadas
# ---------------------------------------------------------------------------
def menu_limpar_coordenadas():
    clear()
    banner()
    macros = cfg.list_macros(WORKSPACE)
    if not macros:
        console.print("[yellow]Nenhum macro cadastrado.[/yellow]")
        pause()
        return

    idx = ask_choice("=== LIMPAR COORDENADAS ===\nEscolha o macro:", macros)
    if idx is None:
        return
    name = macros[idx]
    macro = Macro.from_dict(cfg.load_macro(WORKSPACE, name))

    if not macro.steps:
        console.print("[yellow]Este macro já não tem passos.[/yellow]")
        pause()
        return

    _tabela_passos(macro)

    idx2 = ask_choice(
        "\nO que deseja limpar?",
        ["Remover um passo específico (pelo número)", "Limpar TODOS os passos", "Excluir o macro inteiro"],
    )
    if idx2 is None:
        return

    if idx2 == 0:
        num = ask_text("Número do passo a remover")
        if num.isdigit():
            macro.steps = [s for s in macro.steps if s.id != int(num)]
            cfg.save_macro(WORKSPACE, name, macro.to_dict())
            console.print("[green]Passo removido.[/green]")
    elif idx2 == 1:
        if ask_yes_no(f"Confirma limpar TODOS os passos de '{name}'?", default=False):
            macro.steps = []
            cfg.save_macro(WORKSPACE, name, macro.to_dict())
            console.print("[green]Todos os passos foram removidos.[/green]")
    elif idx2 == 2:
        if ask_yes_no(f"Confirma EXCLUIR o macro '{name}' inteiro?", default=False):
            cfg.delete_macro(WORKSPACE, name)
            console.print("[green]Macro excluído.[/green]")
    pause()


# ---------------------------------------------------------------------------
# 4. Gerenciar Macros (duplicar / exportar / importar / renomear)
# ---------------------------------------------------------------------------
def menu_gerenciar_macros():
    clear()
    banner()
    macros = cfg.list_macros(WORKSPACE)
    idx = ask_choice(
        "=== GERENCIAR MACROS ===",
        [
            "Duplicar um macro existente (reaproveitar para nova demanda)",
            "Renomear um macro",
            "Exportar um macro (.json) para outro caminho",
            "Importar um macro (.json) de outro caminho",
        ],
    )
    if idx is None:
        return

    if idx == 0:
        if not macros:
            console.print("[yellow]Nenhum macro para duplicar.[/yellow]")
            pause()
            return
        i = ask_choice("Escolha o macro a duplicar:", macros)
        if i is None:
            return
        novo_nome = ask_text("Nome do novo macro")
        try:
            cfg.duplicate_macro(WORKSPACE, macros[i], novo_nome)
            console.print(f"[green]Macro duplicado como '{novo_nome}'.[/green]")
        except Exception as e:
            console.print(f"[red]Erro: {e}[/red]")

    elif idx == 1:
        if not macros:
            console.print("[yellow]Nenhum macro para renomear.[/yellow]")
            pause()
            return
        i = ask_choice("Escolha o macro a renomear:", macros)
        if i is None:
            return
        novo_nome = ask_text("Novo nome")
        try:
            cfg.rename_macro(WORKSPACE, macros[i], novo_nome)
            console.print("[green]Macro renomeado.[/green]")
        except Exception as e:
            console.print(f"[red]Erro: {e}[/red]")

    elif idx == 2:
        if not macros:
            console.print("[yellow]Nenhum macro para exportar.[/yellow]")
            pause()
            return
        i = ask_choice("Escolha o macro a exportar:", macros)
        if i is None:
            return
        destino = ask_text(
            "Caminho completo do arquivo de destino (ex: /home/usuario/backup/meu_macro.json)"
        )
        try:
            path = cfg.export_macro(WORKSPACE, macros[i], destino)
            console.print(f"[green]Exportado para: {path}[/green]")
        except Exception as e:
            console.print(f"[red]Erro: {e}[/red]")

    elif idx == 3:
        origem = ask_text("Caminho completo do arquivo .json a importar")
        try:
            nome = cfg.import_macro(WORKSPACE, origem)
            console.print(f"[green]Macro importado como '{nome}'.[/green]")
        except Exception as e:
            console.print(f"[red]Erro: {e}[/red]")

    pause()


# ---------------------------------------------------------------------------
# 5. Cofre de Segredos
# ---------------------------------------------------------------------------
def menu_cofre():
    clear()
    banner()
    console.print("[bold]=== COFRE DE SEGREDOS ===[/bold]")
    console.print(
        "Guarda logins/senhas/tokens usados dentro dos macros de forma "
        "criptografada. Nunca fica em texto puro no JSON do macro nem em log."
    )
    if not VAULT.is_unlocked():
        acao = "Definir a senha mestra (primeiro uso)" if not VAULT.exists() else "Destravar com a senha mestra"
        if not ask_yes_no(f"{acao}. Continuar?", default=True):
            return
        senha = getpass.getpass("Senha mestra: ")
        try:
            VAULT.unlock(senha)
            console.print("[green]Cofre destravado para esta sessão.[/green]")
        except VaultWrongPasswordError as e:
            console.print(f"[red]{e}[/red]")
            pause()
            return

    while True:
        clear()
        banner()
        chaves = VAULT.list_keys()
        console.print("[bold]=== COFRE DE SEGREDOS (destravado) ===[/bold]")
        if chaves:
            for k in chaves:
                console.print(f"  🔒 {k}")
        else:
            console.print("[dim]Nenhum segredo cadastrado ainda.[/dim]")

        idx = ask_choice(
            "\nO que deseja fazer?",
            [
                "Adicionar/atualizar um segredo",
                "Remover um segredo",
                "Travar o cofre e voltar",
            ],
        )
        if idx is None or idx == 2:
            VAULT.lock()
            return
        if idx == 0:
            chave = ask_text("Nome do segredo (ex: senha_sistema_x)")
            valor = getpass.getpass("Valor do segredo (não aparece na tela): ")
            VAULT.set_secret(chave, valor)
            console.print("[green]Segredo salvo (criptografado).[/green]")
            pause()
        elif idx == 1:
            if not chaves:
                pause()
                continue
            i = ask_choice("Qual segredo remover?", chaves)
            if i is not None and ask_yes_no(f"Confirma remover '{chaves[i]}'?", default=False):
                VAULT.delete_secret(chaves[i])
                console.print("[green]Segredo removido.[/green]")
            pause()


# ---------------------------------------------------------------------------
# 6. Agendamentos
# ---------------------------------------------------------------------------
def menu_agendamentos():
    global SCHEDULER
    clear()
    banner()
    console.print("[bold]=== AGENDAMENTOS ===[/bold]")
    console.print("Roda um macro automaticamente em um horário fixo, sem precisar abrir o programa.\n")

    while True:
        clear()
        banner()
        itens = SCHEDULER.load()
        table = Table(title="Agendamentos configurados")
        table.add_column("ID")
        table.add_column("Macro")
        table.add_column("Horário")
        table.add_column("Dias")
        table.add_column("Dados")
        table.add_column("Ativo")
        for it in itens:
            dias = "Todos os dias" if "todos" in it.get("days", ["todos"]) else ", ".join(
                WEEKDAY_LABELS_PT.get(d, d) for d in it["days"]
            )
            table.add_row(
                it["id"], it["macro"], it["time"], dias,
                it.get("data_file") or "-",
                "✅" if it.get("enabled", True) else "⏸️",
            )
        console.print(table)

        idx = ask_choice(
            "\nO que deseja fazer?",
            ["Criar novo agendamento", "Ativar/Desativar um agendamento", "Remover um agendamento", "Voltar"],
        )
        if idx is None or idx == 3:
            return
        if idx == 0:
            macros = cfg.list_macros(WORKSPACE)
            if not macros:
                console.print("[yellow]Nenhum macro cadastrado.[/yellow]")
                pause()
                continue
            i = ask_choice("Qual macro agendar?", macros)
            if i is None:
                continue
            horario = ask_text("Horário (formato 24h, ex: 08:30)")
            usar_dados = ask_yes_no("Rodar com um arquivo de dados em lote?", default=False)
            data_file = None
            if usar_dados:
                ds = DataSource(PATHS["data"])
                arquivos = ds.list_files()
                if arquivos:
                    j = ask_choice("Qual arquivo?", arquivos)
                    data_file = arquivos[j] if j is not None else None
            todos_dias = ask_yes_no("Repetir todos os dias?", default=True)
            dias = ["todos"]
            if not todos_dias:
                nomes_pt = [WEEKDAY_LABELS_PT[d] for d in WEEKDAYS]
                console.print("Escolha os dias (responda os números separados por vírgula, ex: 1,3,5):")
                for n, d in enumerate(nomes_pt, 1):
                    console.print(f"  {n}. {d}")
                raw = ask_text("Dias")
                escolhidos = [int(x.strip()) - 1 for x in raw.split(",") if x.strip().isdigit()]
                dias = [WEEKDAYS[i] for i in escolhidos if 0 <= i < len(WEEKDAYS)] or ["todos"]
            SCHEDULER.add(macros[i], horario, days=dias, data_file=data_file)
            console.print("[green]Agendamento criado.[/green]")
            pause()
        elif idx == 1:
            if not itens:
                pause()
                continue
            ids = [f"{it['id']} - {it['macro']}" for it in itens]
            i = ask_choice("Qual agendamento alternar?", ids)
            if i is not None:
                atual = itens[i]
                SCHEDULER.toggle(atual["id"], not atual.get("enabled", True))
            pause()
        elif idx == 2:
            if not itens:
                pause()
                continue
            ids = [f"{it['id']} - {it['macro']}" for it in itens]
            i = ask_choice("Qual agendamento remover?", ids)
            if i is not None and ask_yes_no("Confirma remover?", default=False):
                SCHEDULER.remove(itens[i]["id"])
            pause()


# ---------------------------------------------------------------------------
# 7. Workspaces (multi-cliente/multi-projeto)
# ---------------------------------------------------------------------------
def menu_workspaces():
    global WORKSPACE, PATHS, logger, VAULT
    clear()
    banner()
    console.print("[bold]=== WORKSPACES ===[/bold]")
    console.print(
        "Cada workspace tem seus próprios macros, dados, logs, relatórios e "
        "cofre de segredos — use um por cliente/projeto diferente.\n"
    )
    workspaces = cfg.list_workspaces()
    for w in workspaces:
        marca = " (ativo)" if w == WORKSPACE else ""
        console.print(f"  📁 {w}{marca}")

    idx = ask_choice(
        "\nO que deseja fazer?",
        ["Trocar de workspace ativo", "Criar novo workspace", "Excluir um workspace", "Voltar"],
    )
    if idx is None or idx == 3:
        return
    if idx == 0:
        i = ask_choice("Qual workspace ativar?", workspaces)
        if i is not None:
            cfg.set_active_workspace(SETTINGS, workspaces[i])
            WORKSPACE = workspaces[i]
            PATHS = cfg.workspace_paths(WORKSPACE)
            logger = setup_logger(PATHS["logs"])
            VAULT = Vault(PATHS["vault"])
            console.print(f"[green]Workspace ativo agora: {WORKSPACE}[/green]")
    elif idx == 1:
        nome = ask_text("Nome do novo workspace")
        try:
            cfg.create_workspace(nome)
            console.print(f"[green]Workspace '{nome}' criado.[/green]")
        except Exception as e:
            console.print(f"[red]Erro: {e}[/red]")
    elif idx == 2:
        candidatos = [w for w in workspaces if w != "default"]
        if not candidatos:
            console.print("[yellow]Não há workspaces (além do 'default') para excluir.[/yellow]")
            pause()
            return
        i = ask_choice("Qual workspace excluir?", candidatos)
        if i is not None and ask_yes_no(f"Confirma EXCLUIR '{candidatos[i]}' e todos os seus dados?", default=False):
            cfg.delete_workspace(candidatos[i])
            console.print("[green]Workspace excluído.[/green]")
    pause()


# ---------------------------------------------------------------------------
# 8. Configurações
# ---------------------------------------------------------------------------
def menu_configuracoes():
    global SETTINGS
    while True:
        clear()
        banner()
        b = SETTINGS["browser"]
        console.print("[bold]=== CONFIGURAÇÕES ===[/bold]")
        console.print(f"1. Navegador: {b['type']}")
        console.print(f"2. Headless (sem janela visível): {b['headless']}")
        console.print(f"3. Tamanho da janela: {b['window_size']}")
        console.print(f"4. Profile do navegador (login salvo): {b['profile_path']}")
        console.print(f"5. Espera implícita (s): {b['implicit_wait']}")
        console.print(f"6. Tentativas em falha transitória (retry): {SETTINGS['default_retries']}")
        console.print(f"7. Screenshot automático em erro: {SETTINGS['screenshot_on_error']}")
        console.print(f"8. Porta da Interface Gráfica: {SETTINGS.get('gui_port', 5757)}")
        console.print("9. Voltar")

        raw = console.input("\nEscolha o item para editar: ").strip()
        if raw == "1":
            idx = ask_choice("Navegador:", ["chrome", "firefox", "edge"])
            if idx is not None:
                b["type"] = ["chrome", "firefox", "edge"][idx]
        elif raw == "2":
            b["headless"] = ask_yes_no(
                "Rodar sem janela visível (recomendado para não atrapalhar seu uso do PC)?",
                default=True,
            )
        elif raw == "3":
            w = ask_text("Largura", default=str(b["window_size"][0]))
            h = ask_text("Altura", default=str(b["window_size"][1]))
            b["window_size"] = [int(w), int(h)]
        elif raw == "4":
            path = ask_text(
                "Caminho absoluto do profile (deixe vazio para nenhum)", allow_empty=True
            )
            b["profile_path"] = path or None
        elif raw == "5":
            b["implicit_wait"] = ask_float("Espera implícita (segundos)", b["implicit_wait"])
        elif raw == "6":
            SETTINGS["default_retries"] = int(
                ask_float("Tentativas extras em falha transitória", SETTINGS["default_retries"])
            )
        elif raw == "7":
            SETTINGS["screenshot_on_error"] = ask_yes_no(
                "Tirar screenshot automático quando um passo falhar definitivamente?",
                default=SETTINGS["screenshot_on_error"],
            )
        elif raw == "8":
            SETTINGS["gui_port"] = int(ask_float("Porta da interface gráfica", SETTINGS.get("gui_port", 5757)))
        elif raw == "9":
            cfg.save_settings(SETTINGS)
            return
        else:
            console.print("[red]Opção inválida.[/red]")
        cfg.save_settings(SETTINGS)


# ---------------------------------------------------------------------------
# 9. Abrir Interface Gráfica
# ---------------------------------------------------------------------------
def menu_abrir_gui():
    porta = SETTINGS.get("gui_port", 5757)
    console.print(f"\n[cyan]Iniciando a interface gráfica em http://127.0.0.1:{porta} ...[/cyan]")

    def _start():
        import gui_app
        gui_app.run_server(porta)

    t = threading.Thread(target=_start, daemon=True)
    t.start()
    time.sleep(1.5)
    try:
        webbrowser.open(f"http://127.0.0.1:{porta}")
    except Exception:
        pass
    console.print(
        f"[green]Interface gráfica rodando em segundo plano.[/green] Se o navegador não "
        f"abrir sozinho, acesse: http://127.0.0.1:{porta}"
    )
    pause()


# ---------------------------------------------------------------------------
# Menu principal
# ---------------------------------------------------------------------------
def main():
    global SCHEDULER
    SCHEDULER = SchedulerManager(
        os.path.join(PATHS["base"], "schedules.json"), _rodar_macro_por_nome
    )
    SCHEDULER.start()

    while True:
        clear()
        banner()
        console.print()
        console.print("  [cyan]1.[/cyan] Executar Macro")
        console.print("  [cyan]2.[/cyan] Marcar Coordenadas (criar/editar/reordenar macro)")
        console.print("  [cyan]3.[/cyan] Limpar Coordenadas")
        console.print("  [cyan]4.[/cyan] Gerenciar Macros (duplicar/exportar/importar/renomear)")
        console.print("  [cyan]5.[/cyan] Cofre de Segredos")
        console.print("  [cyan]6.[/cyan] Agendamentos")
        console.print("  [cyan]7.[/cyan] Workspaces")
        console.print("  [cyan]8.[/cyan] Configurações")
        console.print("  [cyan]9.[/cyan] Abrir Interface Gráfica (navegador)")
        console.print("  [cyan]10.[/cyan] Sair")

        raw = console.input("\nEscolha uma opção: ").strip()
        if raw == "1":
            menu_executar_macro()
        elif raw == "2":
            menu_marcar_coordenadas()
        elif raw == "3":
            menu_limpar_coordenadas()
        elif raw == "4":
            menu_gerenciar_macros()
        elif raw == "5":
            menu_cofre()
        elif raw == "6":
            menu_agendamentos()
        elif raw == "7":
            menu_workspaces()
        elif raw == "8":
            menu_configuracoes()
        elif raw == "9":
            menu_abrir_gui()
        elif raw == "10":
            if RUNNING_THREADS:
                console.print("[yellow]Há execuções em segundo plano. Elas serão interrompidas ao sair.[/yellow]")
                if not ask_yes_no("Confirma saída?", default=False):
                    continue
            console.print("[cyan]Até logo![/cyan]")
            sys.exit(0)
        else:
            console.print("[red]Opção inválida.[/red]")
            time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrompido pelo operador.[/yellow]")
        sys.exit(0)
