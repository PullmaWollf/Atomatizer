"""
gui_app.py
=========================================================
AUTOMATIZER WEB — Interface Gráfica (dashboard local via navegador)
=========================================================
Roda um servidor Flask 100% local (nada sai da sua máquina) para operar
o Automatizer Web sem precisar do terminal: rodar macros, acompanhar log
ao vivo, gerenciar segredos, agendamentos e workspaces.

Pode ser aberto de duas formas:
  1. Pelo atalho (Iniciar_AutomatizerWeb.bat / .sh) — forma recomendada.
  2. Pelo menu do terminal (main.py), opção "Abrir Interface Gráfica".
  3. Diretamente: `python gui_app.py`
"""
import os
import sys
import threading
import webbrowser
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, flash

from core import config_manager as cfg
from core.logger import setup_logger
from core.locator import LocatorType
from core.macro import (
    Macro, MacroStep, MacroExecutor, VALID_ACTIONS, ACTION_LABELS,
    NO_LOCATOR_ACTIONS, VALUE_ACTIONS, CONDITION_TYPES, CONDITION_LABELS,
)
from core.driver_manager import build_driver
from core.data_source import DataSource
from core.vault import Vault, VaultWrongPasswordError
from core.scheduler import SchedulerManager, WEEKDAYS, WEEKDAY_LABELS_PT

app = Flask(__name__)
app.secret_key = "automatizer-web-local-secret"  # só protege a sessão local do próprio navegador

SETTINGS = cfg.load_settings()
APP_NAME = SETTINGS.get("app_name", "Automatizer Web")
WORKSPACE = SETTINGS["active_workspace"]
PATHS = cfg.workspace_paths(WORKSPACE)
logger = setup_logger(PATHS["logs"])
VAULT = Vault(PATHS["vault"])
RUNNING = {}  # nome_macro -> Thread
SCHEDULER = None


def _refresh_workspace(name):
    global WORKSPACE, PATHS, logger, VAULT
    WORKSPACE = name
    PATHS = cfg.workspace_paths(WORKSPACE)
    logger = setup_logger(PATHS["logs"])
    VAULT = Vault(PATHS["vault"])


def _executor_kwargs():
    def _load_macro_fn(name):
        return Macro.from_dict(cfg.load_macro(WORKSPACE, name))

    return dict(
        vault=VAULT if VAULT.is_unlocked() else None,
        load_macro_fn=_load_macro_fn,
        default_retries=int(SETTINGS.get("default_retries", 2)),
        screenshot_on_error=SETTINGS.get("screenshot_on_error", True),
        screenshot_dir=PATHS["screenshots"],
    )


def _run_macro_background(macro: Macro, data_rows, headless_override=None):
    driver = None
    try:
        browser_cfg = dict(SETTINGS["browser"])
        if macro.browser_override:
            browser_cfg.update(macro.browser_override)
        if headless_override is not None:
            browser_cfg["headless"] = headless_override
        driver = build_driver(browser_cfg)
        data_source = DataSource(PATHS["data"])
        executor = MacroExecutor(driver, data_source, **_executor_kwargs())

        if data_rows:
            import csv
            resultados = []
            for i, row in enumerate(data_rows, 1):
                logger.info(f"[{macro.name}] Registro {i}/{len(data_rows)}: {row}")
                try:
                    variaveis = executor.run(macro, data_row=row)
                    resultados.append({"linha": i, "status": "OK", "erro": "", "variaveis_capturadas": variaveis})
                except Exception as e:
                    logger.error(f"[{macro.name}] Registro {i} FALHOU: {e}")
                    resultados.append({"linha": i, "status": "ERRO", "erro": str(e), "variaveis_capturadas": ""})
            os.makedirs(PATHS["reports"], exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(PATHS["reports"], f"{macro.name}_{ts}.csv")
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["linha", "status", "erro", "variaveis_capturadas"])
                w.writeheader()
                for r in resultados:
                    w.writerow(r)
            ok = sum(1 for r in resultados if r["status"] == "OK")
            logger.info(f"[{macro.name}] Lote concluído: {ok}/{len(resultados)} OK. Relatório: {path}")
        else:
            executor.run(macro)
            logger.info(f"[{macro.name}] Execução finalizada com sucesso.")
    except Exception as e:
        logger.error(f"[{macro.name}] ERRO durante a execução: {e}")
    finally:
        if driver:
            driver.quit()
        RUNNING.pop(macro.name, None)


def _run_macro_by_name(macro_name, data_file=None):
    macro = Macro.from_dict(cfg.load_macro(WORKSPACE, macro_name))
    data_rows = None
    if data_file:
        data_rows = DataSource(PATHS["data"]).load_rows(data_file)
    _run_macro_background(macro, data_rows)


def _ensure_scheduler():
    global SCHEDULER
    if SCHEDULER is None:
        SCHEDULER = SchedulerManager(
            os.path.join(PATHS["base"], "schedules.json"), _run_macro_by_name
        )
        SCHEDULER.start()
    return SCHEDULER


# ---------------------------------------------------------------------------
# Contexto compartilhado com todos os templates
# ---------------------------------------------------------------------------
@app.context_processor
def inject_globals():
    return dict(
        app_name=APP_NAME,
        workspace=WORKSPACE,
        running=list(RUNNING.keys()),
        vault_unlocked=VAULT.is_unlocked(),
    )


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@app.route("/")
def dashboard():
    macros = cfg.list_macros(WORKSPACE)
    total_passos = 0
    for m in macros:
        d = cfg.load_macro(WORKSPACE, m)
        total_passos += len(d.get("steps", []))
    itens_agendados = _ensure_scheduler().load()
    return render_template(
        "dashboard.html",
        total_macros=len(macros),
        total_passos=total_passos,
        total_agendamentos=len([i for i in itens_agendados if i.get("enabled", True)]),
        workspaces=cfg.list_workspaces(),
    )


# ---------------------------------------------------------------------------
# Workspaces
# ---------------------------------------------------------------------------
@app.route("/workspaces")
def workspaces_page():
    return render_template("workspaces.html", workspaces=cfg.list_workspaces())


@app.route("/workspaces/switch", methods=["POST"])
def workspaces_switch():
    name = request.form["name"]
    cfg.set_active_workspace(SETTINGS, name)
    _refresh_workspace(name)
    global SCHEDULER
    SCHEDULER = None
    flash(f"Workspace ativo agora: {name}", "success")
    return redirect(url_for("dashboard"))


@app.route("/workspaces/create", methods=["POST"])
def workspaces_create():
    name = request.form["name"].strip()
    try:
        cfg.create_workspace(name)
        flash(f"Workspace '{name}' criado.", "success")
    except Exception as e:
        flash(str(e), "error")
    return redirect(url_for("workspaces_page"))


@app.route("/workspaces/delete", methods=["POST"])
def workspaces_delete():
    name = request.form["name"]
    try:
        cfg.delete_workspace(name)
        flash(f"Workspace '{name}' excluído.", "success")
    except Exception as e:
        flash(str(e), "error")
    return redirect(url_for("workspaces_page"))


# ---------------------------------------------------------------------------
# Macros — listagem, criação, detalhe/edição de passos
# ---------------------------------------------------------------------------
@app.route("/macros")
def macros_list():
    macros = cfg.list_macros(WORKSPACE)
    info = []
    for m in macros:
        d = cfg.load_macro(WORKSPACE, m)
        info.append({"name": m, "url": d.get("start_url", ""), "steps": len(d.get("steps", []))})
    return render_template("macros.html", macros=info)


@app.route("/macros/create", methods=["POST"])
def macros_create():
    name = request.form["name"].strip()
    url = request.form.get("url", "").strip()
    if cfg.macro_exists(WORKSPACE, name):
        flash("Já existe um macro com esse nome.", "error")
        return redirect(url_for("macros_list"))
    macro = Macro(name=name, start_url=url)
    cfg.save_macro(WORKSPACE, name, macro.to_dict())
    flash(f"Macro '{name}' criado.", "success")
    return redirect(url_for("macro_detail", name=name))


@app.route("/macros/<name>/duplicate", methods=["POST"])
def macros_duplicate(name):
    new_name = request.form["new_name"].strip()
    try:
        cfg.duplicate_macro(WORKSPACE, name, new_name)
        flash(f"Macro duplicado como '{new_name}'.", "success")
    except Exception as e:
        flash(str(e), "error")
    return redirect(url_for("macros_list"))


@app.route("/macros/<name>/rename", methods=["POST"])
def macros_rename(name):
    new_name = request.form["new_name"].strip()
    try:
        cfg.rename_macro(WORKSPACE, name, new_name)
        flash("Macro renomeado.", "success")
        return redirect(url_for("macro_detail", name=new_name))
    except Exception as e:
        flash(str(e), "error")
        return redirect(url_for("macro_detail", name=name))


@app.route("/macros/<name>/delete", methods=["POST"])
def macros_delete(name):
    cfg.delete_macro(WORKSPACE, name)
    flash(f"Macro '{name}' excluído.", "success")
    return redirect(url_for("macros_list"))


@app.route("/macros/<name>/export")
def macros_export(name):
    path = cfg.macro_path(WORKSPACE, name)
    return send_file(path, as_attachment=True, download_name=f"{name}.json")


@app.route("/macros/import", methods=["POST"])
def macros_import():
    file = request.files.get("file")
    if not file:
        flash("Nenhum arquivo enviado.", "error")
        return redirect(url_for("macros_list"))
    tmp_path = os.path.join(PATHS["base"], f"_import_tmp_{file.filename}")
    file.save(tmp_path)
    try:
        nome = cfg.import_macro(WORKSPACE, tmp_path)
        flash(f"Macro importado como '{nome}'.", "success")
    except Exception as e:
        flash(str(e), "error")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    return redirect(url_for("macros_list"))


@app.route("/macros/<name>")
def macro_detail(name):
    d = cfg.load_macro(WORKSPACE, name)
    macro = Macro.from_dict(d)
    locator_types = [t.value for t in LocatorType.menu()]
    return render_template(
        "macro_detail.html",
        macro=macro,
        action_labels=ACTION_LABELS,
        valid_actions=VALID_ACTIONS,
        no_locator_actions=NO_LOCATOR_ACTIONS,
        value_actions=VALUE_ACTIONS,
        locator_types=locator_types,
        condition_types=CONDITION_TYPES,
        condition_labels=CONDITION_LABELS,
        other_macros=[m for m in cfg.list_macros(WORKSPACE) if m != name],
        vault_keys=VAULT.list_keys() if VAULT.is_unlocked() else [],
    )


def _step_from_form(form) -> dict:
    action = form["action"]
    d = dict(
        action=action,
        locator_type=form.get("locator_type") or None,
        locator_value=form.get("locator_value") or None,
        fallback_locator_type=form.get("fallback_locator_type") or None,
        fallback_locator_value=form.get("fallback_locator_value") or None,
        value_source=form.get("value_source") or None,
        value=form.get("value") or None,
        variable_name=form.get("variable_name") or None,
        select_by=form.get("select_by") or None,
        optional=form.get("optional") == "on",
        wait_before=float(form.get("wait_before") or 0),
        wait_after=float(form.get("wait_after") or 0),
        timeout=float(form.get("timeout") or 10),
        condition_type=form.get("condition_type") or None,
        condition_locator_type=form.get("condition_locator_type") or None,
        condition_locator_value=form.get("condition_locator_value") or None,
        condition_variable=form.get("condition_variable") or None,
        condition_value=form.get("condition_value") or None,
    )
    if action == "repeat_block":
        d["repeat_from_id"] = int(form["repeat_from_id"]) if form.get("repeat_from_id") else None
        d["repeat_to_id"] = int(form["repeat_to_id"]) if form.get("repeat_to_id") else None
        d["repeat_times"] = int(form["repeat_times"]) if form.get("repeat_times") else None
        d["repeat_while_locator_type"] = form.get("repeat_while_locator_type") or None
        d["repeat_while_locator_value"] = form.get("repeat_while_locator_value") or None
    if action == "call_macro":
        d["value"] = form.get("submacro_name") or None
    return d


@app.route("/macros/<name>/steps/add", methods=["POST"])
def step_add(name):
    d = cfg.load_macro(WORKSPACE, name)
    macro = Macro.from_dict(d)
    data = _step_from_form(request.form)
    step = MacroStep(id=macro.next_id(), **data)
    macro.steps.append(step)
    cfg.save_macro(WORKSPACE, name, macro.to_dict())
    flash(f"Passo #{step.id} adicionado.", "success")
    return redirect(url_for("macro_detail", name=name))


@app.route("/macros/<name>/steps/<int:step_id>/delete", methods=["POST"])
def step_delete(name, step_id):
    d = cfg.load_macro(WORKSPACE, name)
    macro = Macro.from_dict(d)
    macro.steps = [s for s in macro.steps if s.id != step_id]
    cfg.save_macro(WORKSPACE, name, macro.to_dict())
    flash("Passo removido.", "success")
    return redirect(url_for("macro_detail", name=name))


@app.route("/macros/<name>/steps/<int:step_id>/move/<direction>", methods=["POST"])
def step_move(name, step_id, direction):
    d = cfg.load_macro(WORKSPACE, name)
    macro = Macro.from_dict(d)
    macro.move_step(step_id, -1 if direction == "up" else 1)
    cfg.save_macro(WORKSPACE, name, macro.to_dict())
    return redirect(url_for("macro_detail", name=name))


@app.route("/macros/<name>/url", methods=["POST"])
def macro_set_url(name):
    d = cfg.load_macro(WORKSPACE, name)
    macro = Macro.from_dict(d)
    macro.start_url = request.form.get("start_url", "").strip()
    cfg.save_macro(WORKSPACE, name, macro.to_dict())
    flash("URL inicial atualizada.", "success")
    return redirect(url_for("macro_detail", name=name))


# ---------------------------------------------------------------------------
# Executar
# ---------------------------------------------------------------------------
@app.route("/run")
def run_page():
    macros = cfg.list_macros(WORKSPACE)
    arquivos = DataSource(PATHS["data"]).list_files()
    return render_template("run.html", macros=macros, arquivos=arquivos)


@app.route("/run/start", methods=["POST"])
def run_start():
    name = request.form["macro"]
    macro = Macro.from_dict(cfg.load_macro(WORKSPACE, name))
    if name in RUNNING:
        flash(f"O macro '{name}' já está em execução.", "error")
        return redirect(url_for("run_page"))

    data_file = request.form.get("data_file") or None
    data_rows = DataSource(PATHS["data"]).load_rows(data_file) if data_file else None
    ver_navegador = request.form.get("ver_navegador") == "on"
    headless_override = False if ver_navegador else None

    t = threading.Thread(
        target=_run_macro_background, args=(macro, data_rows, headless_override), daemon=True
    )
    RUNNING[name] = t
    t.start()
    flash(f"Macro '{name}' iniciado. Acompanhe em Logs.", "success")
    return redirect(url_for("logs_page"))


# ---------------------------------------------------------------------------
# Logs (ao vivo)
# ---------------------------------------------------------------------------
@app.route("/logs")
def logs_page():
    return render_template("logs.html")


@app.route("/logs/tail")
def logs_tail():
    log_path = os.path.join(PATHS["logs"], "automatizer_web.log")
    if not os.path.exists(log_path):
        return jsonify(lines="(nenhum log ainda)")
    with open(log_path, encoding="utf-8", errors="replace") as f:
        linhas = f.readlines()[-300:]
    return jsonify(lines="".join(linhas))


# ---------------------------------------------------------------------------
# Cofre de Segredos
# ---------------------------------------------------------------------------
@app.route("/vault")
def vault_page():
    return render_template("vault.html", keys=VAULT.list_keys() if VAULT.is_unlocked() else [])


@app.route("/vault/unlock", methods=["POST"])
def vault_unlock():
    senha = request.form["password"]
    try:
        VAULT.unlock(senha)
        flash("Cofre destravado.", "success")
    except VaultWrongPasswordError as e:
        flash(str(e), "error")
    return redirect(url_for("vault_page"))


@app.route("/vault/lock", methods=["POST"])
def vault_lock():
    VAULT.lock()
    flash("Cofre travado.", "success")
    return redirect(url_for("vault_page"))


@app.route("/vault/set", methods=["POST"])
def vault_set():
    if not VAULT.is_unlocked():
        flash("Destrave o cofre primeiro.", "error")
        return redirect(url_for("vault_page"))
    VAULT.set_secret(request.form["key"].strip(), request.form["value"])
    flash("Segredo salvo (criptografado).", "success")
    return redirect(url_for("vault_page"))


@app.route("/vault/delete", methods=["POST"])
def vault_delete():
    VAULT.delete_secret(request.form["key"])
    flash("Segredo removido.", "success")
    return redirect(url_for("vault_page"))


# ---------------------------------------------------------------------------
# Agendamentos
# ---------------------------------------------------------------------------
@app.route("/schedules")
def schedules_page():
    sched = _ensure_scheduler()
    macros = cfg.list_macros(WORKSPACE)
    arquivos = DataSource(PATHS["data"]).list_files()
    return render_template(
        "schedules.html",
        itens=sched.load(),
        macros=macros,
        arquivos=arquivos,
        weekdays=WEEKDAYS,
        weekday_labels=WEEKDAY_LABELS_PT,
    )


@app.route("/schedules/create", methods=["POST"])
def schedules_create():
    sched = _ensure_scheduler()
    dias = request.form.getlist("days") or ["todos"]
    sched.add(
        request.form["macro"],
        request.form["time"],
        days=dias,
        data_file=request.form.get("data_file") or None,
    )
    flash("Agendamento criado.", "success")
    return redirect(url_for("schedules_page"))


@app.route("/schedules/<sid>/toggle", methods=["POST"])
def schedules_toggle(sid):
    sched = _ensure_scheduler()
    itens = {i["id"]: i for i in sched.load()}
    if sid in itens:
        sched.toggle(sid, not itens[sid].get("enabled", True))
    return redirect(url_for("schedules_page"))


@app.route("/schedules/<sid>/delete", methods=["POST"])
def schedules_delete(sid):
    _ensure_scheduler().remove(sid)
    flash("Agendamento removido.", "success")
    return redirect(url_for("schedules_page"))


# ---------------------------------------------------------------------------
# Configurações
# ---------------------------------------------------------------------------
@app.route("/settings")
def settings_page():
    return render_template("settings.html", settings=SETTINGS)


@app.route("/settings/save", methods=["POST"])
def settings_save():
    b = SETTINGS["browser"]
    b["type"] = request.form["browser_type"]
    b["headless"] = request.form.get("headless") == "on"
    b["window_size"] = [int(request.form["width"]), int(request.form["height"])]
    b["profile_path"] = request.form.get("profile_path") or None
    b["implicit_wait"] = float(request.form["implicit_wait"])
    SETTINGS["default_retries"] = int(request.form["default_retries"])
    SETTINGS["screenshot_on_error"] = request.form.get("screenshot_on_error") == "on"
    SETTINGS["gui_port"] = int(request.form["gui_port"])
    cfg.save_settings(SETTINGS)
    flash("Configurações salvas.", "success")
    return redirect(url_for("settings_page"))


# ---------------------------------------------------------------------------
def run_server(port=None, open_browser=False):
    port = port or SETTINGS.get("gui_port", 5757)
    _ensure_scheduler()
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    run_server(open_browser=True)
