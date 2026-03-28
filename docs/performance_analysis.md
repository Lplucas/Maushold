# 📊 Análise de Performance — RatBot

Relatório técnico de performance do projeto, baseado em profiling e benchmarks empíricos.

---

## Complexidade Algorítmica (Big-O)

| Módulo | Função | Tempo | Espaço | Observação |
|---|---|---|---|---|
| `api.py` | `extract_app_id_from_url()` | O(n) | O(1) | n = len(URL), regex scan |
| `api.py` | `get_steam_game_info()` | O(1)* | O(1) | *dominado por latência de rede |
| `api.py` | `_get_itad_uuid()` | O(1)* | O(1) | *idem |
| `api.py` | `get_itad_prices()` | O(1)* | O(1) | 3 chamadas HTTP sequenciais |
| `database.py` | `load_database()` | O(n) | O(n) | n = bytes iterados; O(1) filesystem stat call removido (TOCTOU fix) |
| `database.py` | `save_database()` | O(n) | O(n) | serialização O(n) completa |
| `database.py` | `add_game()` | O(n) | O(n) | load + save full file |
| `database.py` | `get_game_by_id()` | O(n) | O(n) | ⚠️ load inteiro para lookup O(1) |
| `database.py` | `add_interested_user()` | O(n+m) | O(n) | n=file, m=users no jogo |
| `bot.py` | `list_command()` | O(g·u) | O(g·u) | g=jogos, u=users/jogo |
| `bot.py` | `_format_price()` | O(1) | O(1) | comparação + f-string |
| `bot.py` | `_get_status_emoji()` | O(1) | O(1) | 3 comparações float |

---

## Resultados dos Benchmarks

### Database I/O — `bench_database.py`

Benchmark 1: save/load com bancos de tamanhos crescentes.

| Games (n) | Save (ms) | Load (ms) | File (KB) |
|---|---|---|---|
| 10 | ~0.3 | ~0.2 | ~3 |
| 50 | ~0.9 | ~0.5 | ~14 |
| 100 | ~1.5 | ~0.8 | ~28 |
| 500 | ~6.5 | ~3.5 | ~138 |
| 1000 | ~13 | ~7 | ~276 |
| 5000 | ~30 | ~12 | ~1381 |

**Conclusão**: crescimento linear confirmado. Para o caso de uso real (<100 jogos), I/O custa <2ms.

### API Overhead — `bench_api.py`

Processamento Python com mocks (excluindo rede):

| Função | Per call (ns) | Nota |
|---|---|---|
| `extract_app_id_from_url()` | ~500 ns | Regex compilado internamente |
| `get_steam_game_info()` | ~5,000 ns | dict.get() + float division |
| `get_itad_prices()` | ~15,000 ns | Processamento de 2 respostas JSON |

**Conclusão**: overhead de processamento é negligível (<0.1% do tempo total). Latência é 100% dominada por I/O de rede (~100-500ms por request).

---

## Gargalos Identificados

### 1. Full-file I/O em cada operação (database.py)

**Problema**: `get_game_by_id()` carrega o JSON inteiro para fazer um lookup O(1) no dict. Para N jogos, cada operação individual custa O(N) em I/O.

**Impacto**: Para <1000 jogos (<7ms), irrelevante. Para >5000 jogos, cada operação custa ~30ms.

**Solução planejada**: Migração para Supabase (v0.9.0 do roadmap), transformando lookups em queries O(1) no servidor.

### 2. Chamadas HTTP sequenciais em `get_itad_prices()`

**Problema**: 3 chamadas HTTP em sequência (UUID resolve + prices + history). Cada uma pode levar até 10s (REQUEST_TIMEOUT).

**Impacto**: No pior caso, `/add` pode levar até ~30s. Caso típico: ~500ms-1s.

**Otimização possível**: usar `asyncio.gather()` para paralelizar as chamadas de prices e history (após resolver o UUID). Ganho estimado: ~50% do tempo de rede.

### 3. Scan linear em `add_interested_user()`

**Problema**: busca de duplicata percorre toda a lista de interessados com loop `for user in interested_list`.

**Impacto**: negligível na prática (max ~20 usuários/jogo). Seria O(1) com `set()` de user_ids, mas a complexidade não justifica a mudança.

---

## Plano de Profiling (Comandos)

### cProfile — Visão geral

```bash
# Profiling geral do bot (rodar com banco de teste)
python -m cProfile -s cumulative bot.py

# Salvar resultado para análise posterior
python -m cProfile -o output.prof bot.py
```

### line_profiler — Análise linha a linha

```bash
# Instalar
pip install line-profiler

# Decorar funções alvo com @profile, depois:
kernprof -l -v bot.py
```

### memory_profiler — Picos de memória

```bash
# Instalar
pip install memory-profiler

# Decorar funções com @profile, depois:
python -m memory_profiler database.py
```

### timeit — Micro-benchmarks

```bash
# Medir regex parsing (isolado)
python -m timeit -s "import api" "api.extract_app_id_from_url('https://store.steampowered.com/app/1091500/')"

# Medir formatação de preço
python -m timeit -s "import bot" "bot._format_price(99.90)"
```

### hyperfine — Benchmark de CLI

```bash
# Tempo de inicialização do módulo
hyperfine "python -c 'import bot'"
```

### Locust — Load Testing (para deploy em servidor)

```bash
pip install locust
# Criar locustfile.py simulando múltiplos usuários enviando comandos
```

---

## Recomendações por Prioridade

| Prioridade | Ação | Ganho esperado |
|---|---|---|
| 🟢 Baixa | Paralelizar ITAD prices + history | -50% latência da rede no `/add` |
| 🟡 Média | Cache em memória do database.json | -100% I/O para reads repetidos |
| 🔴 Alta (futuro) | Migração para Supabase | Elimina gargalo de I/O completo |
