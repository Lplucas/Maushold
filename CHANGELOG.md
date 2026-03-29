# 📋 Changelog — RatFamilyBot

Registro de todas as versões, implementações, correções e resultados de teste do projeto.
Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/).

---

## [v0.8.0] — 2026-03-29 — Sprint 2: Migração Assíncrona Completa ✅

### Adicionado
- **`aiohttp==3.13.4`** — substitui `requests` para chamadas HTTP não-bloqueantes (Steam + ITAD).
- **`aiofiles==25.1.0`** — I/O de arquivo assíncrono para `database.json`.
- **`STEAM_APP_RE`** — regex compilada (`re.compile`) como constante de módulo em `api.py`, eliminando recompilação a cada chamada de `extract_app_id_from_url()`.
- **`asyncio.gather()`** — chamadas Steam + ITAD agora executam em PARALELO em `_add_game_to_db()`, reduzindo tempo de resposta de ~2s (sequencial) para ~1s (paralelo).
- **Helper `_make_aiohttp_mock()`** em `test_api.py` — encapsula a complexidade de mockar 3 camadas de context managers assíncronos do aiohttp.

### Alterado
- **`database.py` — `open()` → `aiofiles.open()`:** leitura e escrita de `database.json` são agora não-bloqueantes. Padrão: `json.loads(await f.read())` para leitura, `json.dumps()` + `await f.write()` para escrita (minimiza janela de arquivo aberto).
- **`api.py` — `requests` → `aiohttp`:** todas as funções HTTP (`get_steam_game_info`, `_get_itad_uuid`, `get_itad_prices`) são agora `async def`. Exceções mapeadas: `requests.exceptions.Timeout` → `asyncio.TimeoutError`, `requests.exceptions.RequestException` → `aiohttp.ClientError`.
- **`api.py` — sessão compartilhada em `get_itad_prices()`:** as duas chamadas internas (prices + history) compartilham uma única `aiohttp.ClientSession`, reutilizando a conexão TCP.
- **`bot.py` — `_add_game_to_db()` usa `asyncio.gather(return_exceptions=True)`:** se uma das chamadas falhar, a outra continua normalmente. Exceções retornadas como valores são tratadas como `None`.
- **`bot.py` — cabeçalho do módulo atualizado:** documenta arquitetura assíncrona e lista completa de comandos.
- **`test_api.py` — completamente reescrita:** todos os mocks migrados de `@patch("api.requests.get")` para `@patch("api.aiohttp.ClientSession")` com `AsyncMock`.

### Removido
- **`requests==2.31.0`** — removida do `requirements.txt`. Nenhum arquivo `.py` importa `requests` após a migração.

### Nota
- **Verificação anti-falso-positivo:** após cada teste async, quebramos intencionalmente a função testada para confirmar que o teste falha. Método validado em `test_paid_game_success`.

### Resultados
```
test_api.py      → 22 passed ✅ (+4 edge cases)
test_bot.py      → 20 passed ✅ (sem mudanças)
test_database.py → 17 passed ✅ (sem mudanças)
Extras           → 6 passed  ✅
Total: 65/65 testes passando (0.45s)
```

---

## [v0.7.1] — 2026-03-28 — Sprint 1: Correções Críticas ✅

### Corrigido
- **Bug #1 — `await` ausente em `add_command()`:** a chamada `database.add_game()` era uma coroutine não-awaited, resultando em `RuntimeWarning` e jogos que nunca eram salvos. Corrigido via refatoração (ver abaixo).
- **Bug #2 — campo `best_deal_shop` ausente:** `add_command()` não passava o argumento `best_deal_shop` para `database.add_game()`, perdendo a informação da loja com melhor preço. Corrigido via refatoração.

### Alterado
- **`bot.py` — `add_command()` refatorado (DRY):** a função duplicava ~130 linhas de lógica que já existia em `_add_game_to_db()`. Agora delega inteiramente ao helper compartilhado, eliminando duplicação e ambos os bugs de uma vez. A mensagem de confirmação exibida ao usuário permanece igual.
- **`bot.py` — `STATUS_LABELS` extraído para constante:** o dicionário de labels de status (`🔥`, `✅`, `❌`, `❓`) foi movido de variável local em `game_command()` para constante de módulo, permitindo reuso em outros formatadores.
- **`database.py` — `print()` → `logger`:** substituídos todos os 4 `print()` por `logging.getLogger(__name__)` para observabilidade estruturada consistente com `api.py` e `bot.py`.
- **`database.py` — resiliência a JSON corrompido:** `load_database()` agora captura `json.JSONDecodeError` e retorna banco vazio em vez de crashar o bot. Também substituiu `os.path.exists()` por `try/except FileNotFoundError` (padrão Pythônico que evita race conditions TOCTOU).
- **`database.py` — removida dependência de `import os`:** não é mais necessário após remoção de `os.path.exists()`.
- **`test_database.py` — teste de JSON corrompido atualizado:** `test_corrupted_json_raises_error` → `test_corrupted_json_returns_empty`, validando o novo comportamento resiliente.

### Nota
- Type hints em `_format_price()` e `_get_status_emoji()` já existiam no código — confirmado e registrado como satisfeito.

### Resultados
```
test_api.py      → 18 passed ✅
test_bot.py      → 20 passed ✅
test_database.py → 17 passed ✅
Total: 55/55 testes passando (0.34s) — 10 testes extras de módulos adicionais também passaram (65 total)
```

### Arquivos afetados
- `bot.py` [MODIFICADO] — `add_command()` refatorado, `STATUS_LABELS` extraído
- `database.py` [MODIFICADO] — print→logger, JSONDecodeError, FileNotFoundError
- `tests/test_database.py` [MODIFICADO] — teste de JSON corrompido atualizado

---

## [v0.7.0] — 2026-03-17 — Cobertura de Testes & Análise de Performance ✅

### Adicionado
- Expansão da suite de testes de **16 → 55 testes** com cobertura real de caminhos de erro
- **`test_api.py`** — expandido de 6 → 18 testes:
  - Classes organizadas por função: `TestExtractAppIdFromUrl`, `TestGetSteamGameInfo`, `TestGetItadUuid`, `TestGetItadPrices`
  - Novos cenários: timeout, network error, JSON malformado, API key ausente/placeholder, UUID null, deals vazio, histórico ausente, edge cases de URL
- **`test_bot.py`** — expandido de 4 → 20 testes:
  - Classes: `TestFormatPrice`, `TestGetStatusEmoji`, `TestStartCommand`, `TestHelpCommand`, `TestAddCommand`, `TestWantCommand`, `TestGameCommand`, `TestListCommand`
  - Novos cenários: validação de input para todos os comandos (`/add`, `/want`, `/game`, `/list`), edge cases de status emoji
- **`test_database.py`** — expandido de 6 → 17 testes:
  - Classes: `TestLoadDatabase`, `TestSaveDatabase`, `TestAddGame`, `TestGetAllGames`, `TestGetGameById`, `TestAddInterestedUser`
  - Novos cenários: JSON corrupto, preservação UTF-8, chave "games" ausente, username None (fallback), verificação de todos os campos, múltiplos usuários
- **`conftest.py`** — fixtures reutilizáveis `mock_update` e `mock_context`
- Scripts de benchmark (`tests/benchmarks/`):
  - `bench_database.py` — I/O, lookup e scan com bancos de 10 a 5000 jogos
  - `bench_api.py` — overhead de processamento com mocks (excluindo rede)
- Relatório técnico `docs/performance_analysis.md`:
  - Tabela de complexidade Big-O completa
  - Resultados dos benchmarks
  - Gargalos identificados e recomendações

### Corrigido
- `pytest-asyncio` versão inválida corrigida (1.3.0 → 0.23.0) no `requirements.txt`
- Isolamento de testes de database com `asyncio.Lock()` fresco por teste

### Alterado
- `requirements.txt` — adicionado `pytest-cov==6.0.0`, dependências de profiling comentadas
- `.gitignore` — adicionado `htmlcov/`, `*.prof`

### Resultados
```
test_api.py      → 18 passed ✅
test_bot.py      → 20 passed ✅
test_database.py → 17 passed ✅
Total: 55/55 testes passando (0.49s)
```

### Arquivos afetados
- `tests/conftest.py` [MODIFICADO]
- `tests/test_api.py` [MODIFICADO]
- `tests/test_bot.py` [MODIFICADO]
- `tests/test_database.py` [MODIFICADO]
- `tests/benchmarks/bench_database.py` [NOVO]
- `tests/benchmarks/bench_api.py` [NOVO]
- `docs/performance_analysis.md` [NOVO]
- `requirements.txt` [MODIFICADO]
- `.gitignore` [MODIFICADO]

---

## [v0.6.0] — 2026-03-14 — Testes Unitários ✅

### Adicionado
- Suite completa de testes unitários com `pytest` + `pytest-asyncio`
- **`test_api.py`** — 6 testes:
  - `extract_app_id_from_url()` com URLs válidas e inválidas
  - `get_steam_game_info()` — jogo pago, jogo grátis, jogo não encontrado (mocks)
  - `_get_itad_uuid()` — resolução de UUID com mock
  - `get_itad_prices()` — deals e histórico com mocks encadeados
- **`test_bot.py`** — 4 testes:
  - `_format_price()` — preço normal, grátis, sentinela, fallback custom
  - `_get_status_emoji()` — todos os cenários (🔥 / ✅ / ❌ / ❓)
  - `/start` — verifica nome do usuário e mensagem de boas-vindas (async)
  - `/help` — verifica se todos os comandos são listados (async)
- **`test_database.py`** — 6 testes:
  - `load_database()` sem arquivo existente
  - `save_database()` + `load_database()` (round-trip)
  - `add_game()` — novo jogo + duplicata
  - `get_all_games()` — retorno correto
  - `get_game_by_id()` — encontrado + não encontrado
  - `add_interested_user()` — adicionado, duplicata, jogo não encontrado

### Resultados
```
test_api.py      → 6 passed ✅ (0.10s)
test_bot.py      → 4 passed ✅ (0.32s)
test_database.py → 6 passed ✅ (0.05s)
Total: 16/16 testes passando
```

### Arquivos afetados
- `test_api.py` [NOVO]
- `test_bot.py` [NOVO]
- `test_database.py` [NOVO]

---

## [v0.5.0] — 2026-02-24 — Comando `/game` ✅

### Adicionado
- Comando `/game [AppID]` — mostra detalhes completos de um jogo específico:
  - Preços: Steam, melhor deal atual (via ITAD), mínimo histórico
  - Status com label descritivo (🔥 MENOR PREÇO HISTÓRICO / ✅ Bom preço / ❌ Aguardar)
  - Lista numerada de todos os interessados
  - Cálculo de preço por pessoa

### Edge cases tratados
- Sem argumento → instruções de uso
- URL da Steam ao invés de AppID → detecta e sugere o comando correto (UX)
- Texto não numérico → erro com exemplo
- AppID não encontrado no banco → sugere usar `/add`
- Jogo sem interessados → mensagem amigável
- Jogo sem dados de preço → exibe "N/D"

### Arquivos afetados
- `bot.py` — função `game_command()` (linhas 669–806)

---

## [v0.4.0] — 2026-02-24 — Comando `/list` ✅

### Adicionado
- Comando `/list` — lista formatada de todos os jogos rastreados:
  - Status emoji (🔥 / ✅ / ❌ / ❓) com lógica de avaliação de deals
  - Preços: Steam, melhor deal (com nome da loja), mínimo histórico
  - Contagem de interessados com nomes inline
  - Preço por pessoa (melhor preço disponível ÷ nº de interessados)
- Helpers compartilhados:
  - `_format_price()` — formatação consistente de preços BRL
  - `_get_status_emoji()` — avaliação de deals em 3 níveis

### Edge cases tratados
- Banco de dados vazio → mensagem de onboarding amigável
- Jogos grátis → mostra "Grátis 🎉"
- Sem dados ITAD → mostra "N/D"
- Ninguém interessado → "Ninguém ainda"
- Mensagem longa → paginação respeitando limite de 4096 chars do Telegram

### Arquivos afetados
- `bot.py` — funções `list_command()`, `_format_price()`, `_get_status_emoji()`

---

## [v0.3.0] — 2026-02-24 — Comando `/want` ✅

### Adicionado
- Comando `/want [AppID | URL]` — registrar interesse em rachar um jogo:
  - **PATH A (URL da Steam):** busca dados, adiciona ao banco se necessário, registra interesse automaticamente
  - **PATH B (AppID numérico):** registra interesse se o jogo já está no banco
- Helper DRY `_add_game_to_db()` — compartilha lógica de busca entre `/add` e `/want`
- Cálculo automático de divisão de custo por pessoa
- Exibição da lista de interessados na confirmação

### Edge cases tratados
- Sem argumento → instruções com exemplos dos dois modos
- Texto inválido (nem URL nem número) → erro amigável
- Falha na Steam API → abort com mensagem clara
- Interesse duplicado → aviso "Você já está no racha"
- Usuário sem @username → fallback para `first_name`
- Jogo não encontrado (AppID manual) → sugere usar `/add` ou `/want` com URL

### Arquivos afetados
- `bot.py` — funções `want_command()`, `_add_game_to_db()`
- `database.py` — função `add_interested_user()`

---

## [v0.2.0] — 2026-02-24 — Comando `/add` + Integrações de API ✅

### Adicionado
- Comando `/add [URL da Steam]` — adicionar jogo ao banco de dados:
  - Valida e extrai AppID da URL via regex
  - Busca nome e preço oficial via **Steam Storefront API** (BRL)
  - Busca melhor deal atual e mínimo histórico via **ITAD API** (BRL)
  - Salva no banco de dados JSON
  - Mensagem de confirmação detalhada com 3 fontes de preço
- Módulo `api.py` completo:
  - `extract_app_id_from_url()` — parser de URLs da Steam
  - `get_steam_game_info()` — nome + preço (Steam API, cc=br)
  - `_get_itad_uuid()` — resolve Steam AppID → ITAD UUID
  - `get_itad_prices()` — melhor deal + histórico (ITAD API, country=BR)
- Módulo `database.py` completo:
  - `load_database()` / `save_database()` — I/O de JSON com `asyncio.Lock`
  - `add_game()` — inserção com detecção de duplicata
  - `get_all_games()` / `get_game_by_id()` — consultas

### Edge cases tratados
- Sem URL fornecida → instruções de uso
- URL não-Steam → erro com exemplo
- AppID não encontrado na Steam → abort claro
- ITAD indisponível → salva com valor sentinela (-1.0, "N/D")
- Jogo já no banco → aviso de duplicata
- Jogos grátis → preço $0.00 tratado corretamente
- Timeout nas APIs → tratamento com `REQUEST_TIMEOUT = 10s`

### Arquivos afetados
- `api.py` [NOVO]
- `database.py` [NOVO]
- `bot.py` — função `add_command()`

---

## [v0.1.0] — 2026-02-24 — Setup Inicial ✅

### Adicionado
- Estrutura base do projeto
- Arquivo `bot.py` com:
  - Configuração de logging
  - Carregamento de variáveis de ambiente (`.env`)
  - Conexão com API do Telegram via `python-telegram-bot v21.6`
  - Comando `/start` — mensagem de boas-vindas personalizada
  - Comando `/help` — lista detalhada de comandos disponíveis
  - Entry point com `run_polling()`
- Arquivo `requirements.txt` com dependências:
  - `python-telegram-bot==21.6`
  - `requests==2.31.0`
  - `python-dotenv==1.0.0`
  - `pytest==9.0.2`, `pytest-asyncio==1.3.0`
- Arquivo `.env` (template) com `BOT_TOKEN` e `ITAD_API_KEY`
- Arquivo `.gitignore` completo (secrets, cache, venvs, IDEs, OS junk)
- Arquivo `README.md` com:
  - Estrutura do projeto
  - Diagrama de arquitetura (Mermaid)
  - Instruções de configuração e execução
  - Tabela de comandos com status

### Arquivos afetados
- `bot.py` [NOVO]
- `.env` [NOVO]
- `.gitignore` [NOVO]
- `requirements.txt` [NOVO]
- `README.md` [NOVO]

---

# 🗺️ Roadmap — Próximos Passos (Refatoração v3.0 e Evolução)

O roadmap foi reestruturado com base na **Análise Técnica v3.0**, priorizando a estabilidade, refatoração de I/O assíncrono e arquitetura limpa antes das features em nuvem. Cada ciclo foca em ganho mensurável no código e facilidade de teste continuo.

## Fase 1 — Estabilidade e Assincronicidade (Sprints 1 e 2) ✅
### v0.9.0 — Async Completo & Correção Crítica
- [ ] **Correção de Bugs:** Inclusão de `await` e campo `best_deal_shop` nas funções de add do `bot.py`
- [ ] **Rede Async:** Substituir `requests` bloqueante por `aiohttp` na `api.py`
- [ ] **I/O Async:** Substituir `open()` síncrono por `aiofiles` na `database.py` com `try-except json.JSONDecodeError` contra arquivos corrompidos
- [ ] **Paralelismo:** Implementar `asyncio.gather()` para buscar preços Steam + ITAD em simultâneo (~4s para ~2s)
- [ ] **Otimização Regex:** Usar `re.compile(r"/app/(\d+)")` constante global em `api.py`

## Fase 2 — Arquitetura Pydantic, Repositories e Services (Sprints 3 e 4) 📋
### v0.10.0 — Desacoplamento do Domínio
- [ ] Centralizar e validar variáveis de ambiente no modelo `Settings` (`Pydantic BaseSettings` em `config.py`)
- [ ] Modelar estruturas usando tipagem forte (ex: classes `Game`, `PriceSnapshot`, `InterestedUser` e `TelegramUser` nativas com Pydantic v2)
- [ ] Extrair lógica da base `database.py` implementando classes Repository pattern em `repository/`
- [ ] Extrair lógica das chamadas externas `api.py` criando a Service layer (`game_service.py`, `price_service.py`) no diretório `services/`
- [ ] Injetar estes Services nos Handlers isolados no `bot.py`, reduzindo a duplicação e concentrando a lógica em helpers em `bot/formatters.py`

## Fase 3 — Banco de Dados ORM e Nuvem (Sprints 5 e 6) 📋
### v1.0.0 — Migração Nuvem Supabase
- [ ] Modelar schema relacional com ORM (SQLAlchemy 2.0 + engine asyncpg)
- [ ] Gerenciar histórico e criar/popular tabelas com Alembic
- [ ] Criar views (como `games_current_prices`) nativas do Postgres diretamente no script via Supabase
- [ ] Modificar o Composition root e injeção do repositório para apontar pro `SupabaseGameRepository` (migração total one-time db.json -> cloud)
### v1.1.0 — Deploy
- [ ] Empacotar aplicação limpa (`Dockerfile`)
- [ ] Realizar provisionamento Cloud Deploy do bot rodando auto-restart (`Oracle Cloud Free Tier` / VM ARM ou `Railway`)

## Fase 4 — Complementos de Funcionalidade (Pós-Arquitetura) 📋
### v1.1.5 — Comandos Administrativos (CRUD)
- [ ] **`/delete [AppID]`** — deletar jogos específicos da lista.
- [ ] **`/unwant [AppID]`** — usuário pode sair do racha de um jogo informando apenas o AppID.
- [ ] **`/update [AppID]`** — atualizar o preço atual de um jogo específico buscando novamente na Steam e ITAD.
- [ ] **`/all2date`** — atualizar iterativamente os preços de TODOS os jogos acompanhados na base de dados.

## Fase 5 — Features Avançadas (Sprints 8 e 9) 📋
### v1.2.0 — Scheduler e Notificações (Jobs)
- [ ] Implementar Job automático para rotina cronológica (`Apscheduler` ou `JobQueue` lib do telegram bot)
- [ ] Mandar mensagens privadas ativas para times com *interested users* com drops de Historical Low
### v1.3.0 — Dashboard Web Estático Public
- [ ] Página read-only via API REST gerada no Vercel (ex: UI usando React + recharts lendo views Supabase sem auth)
- [ ] Implementar no Telegram features inline como InlineKeyboard para interação

---

> **Legenda de status:** ✅ Concluído | 🚧 Em desenvolvimento | 📋 Planejado
