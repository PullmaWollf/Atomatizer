"""
teste_workspaces_e_agendador.py
Testa o CRUD de macros dentro de workspaces isolados e o agendador,
usando arquivos reais em uma pasta temporária (não mexe no projeto real).
"""
import sys, os, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


tmp_base = tempfile.mkdtemp(prefix="automatizer_web_test_")
try:
    # Isola o teste: aponta BASE_DIR/WORKSPACES_DIR para uma pasta temporária
    from core import config_manager as cfg
    cfg.BASE_DIR = tmp_base
    cfg.SETTINGS_PATH = os.path.join(tmp_base, "settings.json")
    cfg.WORKSPACES_DIR = os.path.join(tmp_base, "workspaces")

    print("\n[1] Workspaces")
    cfg.ensure_workspace("default")
    cfg.create_workspace("cliente_a")
    cfg.create_workspace("cliente_b")
    check("3 workspaces existem (default, cliente_a, cliente_b)", set(cfg.list_workspaces()) == {"default", "cliente_a", "cliente_b"})

    try:
        cfg.create_workspace("cliente_a")
        check("não deveria permitir criar workspace duplicado", False)
    except FileExistsError:
        check("bloqueou criação de workspace duplicado", True)

    print("\n[2] Isolamento de macros entre workspaces")
    cfg.save_macro("cliente_a", "fluxo_x", {"name": "fluxo_x", "start_url": "", "steps": []})
    check("macro existe em cliente_a", cfg.macro_exists("cliente_a", "fluxo_x"))
    check("mesmo macro NÃO existe em cliente_b (isolamento)", not cfg.macro_exists("cliente_b", "fluxo_x"))

    print("\n[3] CRUD de macro")
    cfg.duplicate_macro("cliente_a", "fluxo_x", "fluxo_x_copia")
    check("duplicação criou uma cópia", cfg.macro_exists("cliente_a", "fluxo_x_copia"))
    cfg.rename_macro("cliente_a", "fluxo_x_copia", "fluxo_y")
    check("renomear funcionou", cfg.macro_exists("cliente_a", "fluxo_y") and not cfg.macro_exists("cliente_a", "fluxo_x_copia"))
    cfg.delete_macro("cliente_a", "fluxo_y")
    check("exclusão funcionou", not cfg.macro_exists("cliente_a", "fluxo_y"))

    print("\n[4] Excluir workspace (não pode excluir 'default')")
    try:
        cfg.delete_workspace("default")
        check("não deveria permitir excluir 'default'", False)
    except ValueError:
        check("bloqueou exclusão do workspace 'default'", True)
    cfg.delete_workspace("cliente_b")
    check("workspace 'cliente_b' excluído com sucesso", "cliente_b" not in cfg.list_workspaces())

    print("\n[5] Agendador (persistência e toggle)")
    from core.scheduler import SchedulerManager
    chamadas = []
    sched = SchedulerManager(os.path.join(tmp_base, "schedules.json"), lambda m, d: chamadas.append((m, d)))
    item = sched.add("fluxo_x", "08:00", days=["todos"], data_file=None)
    check("agendamento foi salvo", len(sched.load()) == 1)
    sched.toggle(item["id"], False)
    check("agendamento foi desativado", sched.load()[0]["enabled"] is False)
    sched.remove(item["id"])
    check("agendamento foi removido", len(sched.load()) == 0)

    print("\n[6] Cofre: senha errada deve ser rejeitada")
    from core.vault import Vault, VaultWrongPasswordError
    vdir = os.path.join(tmp_base, "vault_test")
    v1 = Vault(vdir)
    v1.unlock("senha-correta")
    v1.set_secret("token_api", "abc123")
    v2 = Vault(vdir)
    try:
        v2.unlock("senha-errada")
        check("deveria ter rejeitado senha errada", False)
    except VaultWrongPasswordError:
        check("rejeitou corretamente a senha mestra errada", True)
    v3 = Vault(vdir)
    v3.unlock("senha-correta")
    check("com a senha certa, o segredo é recuperado corretamente", v3.get_secret("token_api") == "abc123")

finally:
    shutil.rmtree(tmp_base, ignore_errors=True)

print(f"\n=== RESULTADO: {ok_count} OK, {fail_count} FALHAS ===")
sys.exit(1 if fail_count else 0)
