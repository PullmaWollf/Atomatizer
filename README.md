# ⚡ Automatizer Web

Ferramenta genérica de automação de navegador (Selenium) **white label**:
o código nunca muda — só o *macro* (fluxo de passos) muda para atender
qualquer sistema, qualquer cliente, qualquer processo repetitivo.

Este projeto era o "ticket_automation" e passou por uma evolução completa:
renomeado, com interface gráfica, cores no terminal, cofre de credenciais,
lógica condicional/laços/sub-macros, seletor alternativo (self-healing) e
agendador embutido.

---

## Como abrir (atalho — recomendado)

**Windows:** dê duplo clique em **`Iniciar_AutomatizerWeb.bat`**
**Mac:** dê duplo clique em **`Iniciar Automatizer Web.command`**
**Linux:** rode `./iniciar_automatizer_web.sh`

Na primeira vez, o atalho cria um ambiente virtual Python (`venv`) e instala
tudo sozinho — só é necessário ter Python 3.10+ instalado. Da segunda vez em
diante, abre direto. Isso abre a **interface gráfica no navegador**
(`http://127.0.0.1:5757`).

Se preferir o menu colorido no terminal em vez da interface gráfica, use
`Iniciar_AutomatizerWeb_Terminal.bat` (Windows) ou
`iniciar_automatizer_web_terminal.sh` (Mac/Linux). Dentro da interface
gráfica também dá pra rodar tudo — CLI e GUI compartilham os mesmos macros,
workspaces e configurações (são a mesma "fonte de verdade" em disco).

### Criar um atalho na área de trabalho
- **Windows:** clique direito no `.bat` → Enviar para → Área de trabalho (criar atalho).
- **Mac:** arraste o `.command` para o Dock, ou crie um alias na Área de Trabalho.
- **Linux:** copie `automatizer_web.desktop` (crie um a partir do `.sh` com seu ambiente gráfico) ou crie um lançador apontando para o `.sh`.

---

## O que há de novo em relação ao "ticket_automation"

| Antes | Agora |
|---|---|
| Só terminal | **Interface gráfica** (dashboard web local) + terminal colorido (`rich`) |
| Sem atalho | Atalho de 1 clique (`.bat` / `.sh` / `.command`) que instala e abre sozinho |
| Senha/login em texto puro se alguém adicionasse | **Cofre de credenciais criptografado** (PBKDF2 + Fernet/AES), nunca em log/relatório |
| Macro só linear | **Condicional** (`if elemento presente/ausente`, `if variável = / ≠`), **laço** (`repeat_block`) e **sub-macro** (`call_macro`) |
| 1 seletor por passo | **Seletor alternativo** (self-healing leve): se o principal falhar, tenta o backup antes de desistir |
| 1 execução manual por vez | **Agendador** embutido (roda macros automaticamente em horário fixo, todo dia ou dias específicos) |
| Uma pasta só para tudo | **Workspaces**: um espaço isolado (macros/dados/logs/relatórios/cofre) por cliente ou projeto |

---

## Estrutura do projeto

```
automatizer_web/
├── main.py                  # Menu colorido no terminal (rich)
├── gui_app.py                # Interface gráfica (Flask) — dashboard local
├── Iniciar_AutomatizerWeb.bat / .sh / .command   # Atalhos
├── requirements.txt
├── core/
│   ├── macro.py               # Macro + MacroExecutor (ações, condição, laço, sub-macro, fallback)
│   ├── config_manager.py      # Configurações globais + workspaces + CRUD de macro
│   ├── driver_manager.py      # Cria o WebDriver (Chrome/Firefox/Edge)
│   ├── data_source.py         # Lê CSV/JSON/TXT como dados em lote
│   ├── locator.py             # Tipos de localizador (ID, XPATH, CSS...)
│   ├── logger.py              # Log colorido + mascaramento automático de segredos
│   ├── vault.py                # Cofre de credenciais criptografado
│   └── scheduler.py            # Agendador tipo cron em segundo plano
├── templates/ + static/       # HTML/CSS da interface gráfica
├── workspaces/
│   └── default/
│       ├── macros/            # Um .json por macro
│       ├── data/               # CSV/JSON/TXT para execução em lote
│       ├── logs/                # Log + screenshots de erro
│       ├── reports/             # Relatório .csv de cada lote executado
│       └── vault/                # Cofre criptografado (vault.enc + vault.salt)
└── tests/
    ├── teste_manual_novas_features.py     # Condicional, laço, fallback, cofre, sub-macro
    ├── teste_workspaces_e_agendador.py    # Workspaces, CRUD de macro, agendador, cofre
    └── rodar_todos_os_testes.py            # Roda tudo de uma vez
```

Rodar os testes (não depende de pytest, só do `requirements.txt`):
```bash
python tests/rodar_todos_os_testes.py
```

---

## Conceitos novos, na prática

### Cofre de segredos
Vá em **Cofre de Segredos**, defina uma senha mestra na primeira vez e
cadastre `senha_sistema_x`. Em qualquer passo do tipo "digitar", escolha
origem do valor = **"Cofre de segredos"** e selecione a chave. A senha
real nunca é escrita no `.json` do macro nem aparece em log — só a chave
(`senha_sistema_x`) fica salva; o valor é resolvido em memória a cada
execução.

### Condicional
Em qualquer passo, marque "condicional" e escolha, por exemplo,
*"só executar se um elemento estiver AUSENTE"* — útil para pular uma
etapa quando um aviso/popup não aparece, sem quebrar o macro.

### Laço (repeat_block)
Um passo especial que repete um intervalo de passos (por id) N vezes, ou
enquanto um elemento continuar na tela — com um limite de segurança de
500 iterações contra loop infinito.

### Sub-macro (call_macro)
Um passo pode chamar outro macro inteiro (ex.: um macro `fazer_login`
reaproveitado por vários fluxos diferentes), com um limite de 5 chamadas
aninhadas contra chamada circular.

### Seletor alternativo (self-healing leve)
Cada passo pode ter um segundo seletor de reserva. Se o principal não for
encontrado a tempo, o segundo é tentado automaticamente antes de o macro
falhar — reduz manutenção quando o HTML do sistema-alvo muda um pouco.

### Workspaces
Use um workspace por cliente/projeto (**Workspaces** no menu). Cada um
tem macros, dados, logs, relatórios e cofre totalmente isolados dos
outros.

---

## O que fica para uma próxima evolução

Para ser transparente: o pedido original também incluía itens que não
cabem numa entrega de código só — ou que exigem infraestrutura além de
"um programa que roda na sua máquina". Ficam registrados como próximos
passos, na ordem que faria mais sentido atacar:

1. **Gravador de seletor via extensão de navegador** — hoje o seletor
   (XPath/CSS) ainda é digitado à mão na Interface Gráfica ou no menu;
   o próximo salto de usabilidade é clicar no elemento e o seletor vir
   sozinho.
2. **Motor alternativo (Playwright)** — Selenium continua sendo o motor
   único; plugar Playwright como opção ajudaria em sites mais modernos.
3. **Empacotamento em executável único** (PyInstaller) para não depender
   de o usuário ter Python instalado — hoje o atalho ainda cria um `venv`
   e usa o Python do sistema.
4. **Execução distribuída/nuvem** (Selenium Grid, browser na nuvem) para
   volumes grandes — hoje roda sempre na máquina local.
5. **RBAC completo / múltiplos usuários com login** — hoje cada pessoa
   que abre o programa tem acesso total ao workspace ativo.

Essas cinco são as que eu recomendaria priorizar a seguir, em ordem.
