# Automação Web — Framework White Label (Selenium + Python)

Ferramenta genérica de automação de navegador. O código nunca muda entre
tarefas diferentes — o que muda é o **macro** (arquivo de configuração
JSON), criado interativamente pelo menu. Serve para qualquer processo
repetitivo em qualquer sistema web: criação de tickets, cadastro em
massa, prospecção, validação de dados, o que for.

## Estrutura do projeto

```
ticket_automation/
├── main.py                    # Menu interativo (ponto de entrada)
├── settings.json              # Configurações globais (criado automaticamente)
├── requirements.txt
├── core/
│   ├── locator.py             # Os 8 tipos de localizador do Selenium (ID, XPATH, CSS...)
│   ├── driver_manager.py      # Cria o navegador (Chrome/Firefox/Edge, headless, profile)
│   ├── data_source.py         # Lê arquivos CSV/JSON/TXT da pasta data/
│   ├── macro.py               # Estrutura do macro + executor (22 ações, retry, variáveis)
│   ├── config_manager.py      # CRUD, duplicação, exportação/importação de macros
│   └── logger.py              # Log em console + arquivo rotativo
├── macros/                    # Um arquivo .json por automação criada
├── data/                      # Seus arquivos de dados (nomes, números, anexos)
├── logs/                      # automacao.log + screenshots/ (capturas em erro)
├── reports/                   # Um .csv por execução em lote (sucesso/erro por linha)
└── tests/                     # Suíte de testes unitários (51 testes, sem precisar de navegador)
```

## Instalação

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Não é necessário baixar chromedriver manualmente — o Selenium 4.6+
resolve isso sozinho (Selenium Manager).

## Rodando os testes (recomendado antes do primeiro uso real)

```bash
python -m unittest discover -s tests -v
```

51 testes validam toda a lógica do executor (cada uma das 22 ações,
retry automático, modo opcional, screenshot em erro, resolução de
valores, templates, CRUD de macros) usando mocks do Selenium — não abrem
navegador, então rodam em qualquer máquina em segundos.

## Uso

```bash
python main.py
```

Menu principal:

1. **Executar Macro** — roda uma automação já configurada. Pode repetir
   o mesmo macro para cada linha de um arquivo de dados, gerando ao
   final um **relatório CSV** (`reports/`) com sucesso/erro por linha e
   as variáveis capturadas em cada execução. Pode rodar em modo
   **daemon** (thread em segundo plano) ou, se quiser depurar, com a
   janela do navegador visível só naquela execução.
2. **Marcar Coordenadas** — cria um macro novo, edita um existente,
   **edita passos já criados** ou **reordena** a sequência. Para cada
   passo você escolhe o **localizador** (os 8 tipos do Selenium) e a
   **ação** — veja a lista completa abaixo.
3. **Limpar Coordenadas** — remove um passo específico, limpa todos os
   passos de um macro, ou exclui o macro inteiro.
4. **Gerenciar Macros** — **duplica** um macro (para reaproveitar uma
   automação parecida numa nova demanda sem recomeçar do zero),
   **renomeia**, **exporta** para um caminho externo (backup/enviar a um
   colega) e **importa** um `.json` de outro lugar do sistema.
5. **Configurações** — navegador, modo headless, tamanho de janela,
   profile do navegador (login salvo), timeout implícito, pasta de
   dados/logs/relatórios, número de tentativas automáticas em falha
   transitória e se deve tirar screenshot ao errar.

## As 22 ações disponíveis

| Categoria | Ações |
|---|---|
| Mouse | `click`, `double_click`, `right_click`, `hover` |
| Teclado | `type`, `press_key` (ENTER, TAB, ESC, setas...), `clear` |
| Formulário | `select` (dropdown por texto/valor/índice), `upload_file` |
| Navegação | `scroll_to`, `switch_to_frame`, `switch_to_default_content`, `switch_to_window` (abas) |
| Alertas nativos do JS | `accept_alert`, `dismiss_alert`, `type_in_alert` (prompt) |
| Dados | `extract` (captura texto/atributo em uma variável), `execute_js` (roda JS e opcionalmente captura o retorno) |
| Depuração | `screenshot` |
| Fluxo | `wait`, `wait_for_element`, `wait_manual` (pausa para o operador resolver CAPTCHA/2FA manualmente) |

Qualquer passo com localizador pode ser marcado como **opcional**: se o
elemento não existir naquela execução, o macro segue em frente em vez de
falhar — útil para campos condicionais que nem sempre aparecem.

## Variáveis capturadas (encadeando telas)

Um passo `extract` ou `execute_js` pode guardar um valor (ex: o número
do ticket gerado após salvar) numa variável nomeada. Passos posteriores
podem usar esse valor de duas formas:
- origem "Variável capturada", apontando o nome da variável;
- ou embutido em qualquer texto fixo com `{{nome_da_variavel}}`, ex:
  `"Ticket confirmado: {{ticket_id}}"`.

Isso permite fluxos como: criar o ticket → extrair o número gerado →
usar esse número numa tela de confirmação ou registrar no relatório.

## Robustez

- **Retry automático**: falhas transitórias (elemento ainda não pronto,
  clique interceptado, elemento "stale") são tentadas novamente
  automaticamente antes de desistir (configurável em Configurações).
- **Screenshot em erro**: quando um passo falha definitivamente, um
  print da tela é salvo em `logs/screenshots/` para você entender o que
  aconteceu numa execução headless/desatendida.
- **Relatório por linha**: em execuções em lote, cada linha do arquivo
  de dados gera um resultado (OK/ERRO) no CSV de relatório, sem que uma
  falha isolada interrompa o processamento das demais.
- **Log rotativo**: todo o histórico fica em `logs/automacao.log`.

## Por que headless não atrapalha seu uso do computador

Com `headless = true` (padrão), o Chrome roda **sem nenhuma janela
visível na tela**. Como não existe janela, ele fisicamente não pode
roubar o foco do seu mouse ou teclado — você continua digitando e
navegando normalmente em qualquer outro programa enquanto a automação
roda em segundo plano (thread daemon). Use "ver o navegador rodando"
(oferecido na tela de Executar Macro) só quando quiser depurar um macro
novo.

## Exemplo prático (Miss Make / Microvix)

1. Coloque um CSV como `data/exemplo_tickets.csv` com as colunas que o
   formulário de abertura de ticket exige (cliente, titulo, descricao,
   anexo).
2. Em **Marcar Coordenadas**, crie o macro `criar_ticket_missmake`,
   aponte a URL de login/abertura de chamado, e monte os passos:
   digitar `cliente`, digitar `titulo`, digitar `descricao`, enviar
   `anexo` (upload_file), clicar em salvar, `extract` o número do
   ticket gerado numa variável `ticket_id`.
3. Em **Executar Macro**, escolha esse macro, use o arquivo de dados —
   o macro roda uma vez por linha, criando um ticket por cliente e
   gerando um relatório com o resultado de cada um.
4. Precisa de uma variação parecida para outro cliente/fluxo? Em
   **Gerenciar Macros → Duplicar**, clone `criar_ticket_missmake` e
   ajuste só o que for diferente — sem recomeçar do zero.

## Limitações conhecidas

- Este projeto foi validado com uma suíte de 51 testes unitários que
  simulam o navegador (mocks). Isso garante que toda a lógica interna
  está correta, mas **não substitui um teste com o navegador real** na
  sua máquina, contra o sistema web de verdade — os seletores (IDs,
  XPaths etc.) de cada sistema são específicos daquele HTML e precisam
  ser conferidos por você ao montar cada macro.
- `wait_manual` pausa a thread daemon aguardando ENTER no terminal; se
  você rodar vários macros simultâneos em segundo plano, evite usar
  `wait_manual` em mais de um ao mesmo tempo (a leitura do teclado é
  compartilhada pelo terminal).
