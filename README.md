# RatFamilyBot 🐀

Um bot para o Telegram que substitui a planilha compartilhada para racharem jogos da Steam!

## Estrutura do Projeto
```text
RatBot/
├── bot.py                 # Arquivo principal — conecta ao Telegram, recebe comandos e orquestra chamadas assíncronas
├── api.py                 # Comunicação externa (Steam API e ITAD API) via requisições aiohttp (Non-blocking)
├── formatters.py          # Formatação centralizada de mensagens e desativação de link previews
├── database.py            # Toda a lógica de leitura/escrita do banco de JSON de forma assíncrona com aiofiles
├── database.json          # Criado automaticamente na primeira execução
│
├── tests/                 # Testes unitários (pytest) — 121 testes
│   ├── conftest.py        # Fixtures reutilizáveis (mock_update, mock_context)
│   ├── test_api.py        # 22 testes — URLs, Steam API, ITAD, erros, mock assíncrono
│   ├── test_bot.py        # 24 testes — todos os comandos + helpers
│   ├── test_database.py   # 15 testes — CRUD, edge cases, resiliência
│   ├── test_formatters.py # 60 testes — formatação visual das mensagens
│   └── benchmarks/        # Scripts de performance
│       ├── bench_database.py  # I/O, lookup, scan benchmarks
│       └── bench_api.py       # Overhead de processamento de API
│
├── docs/                  # Documentação técnica
│   └── performance_analysis.md  # Análise Big-O e resultados de benchmark
├── notebooks/             # Notebooks de experimentação
│   └── teste.ipynb
│
├── CHANGELOG.md           # Histórico de versões e roadmap do projeto
├── README.md              # Este arquivo
├── requirements.txt       # Dependências do projeto
├── .env                   # Seu Token do Telegram e Chave do ITAD (NUNCA compartilhe!)
└── .gitignore             # Arquivos ignorados pelo Git
```

### Arquitetura do Sistema

```mermaid
%%{init:{'theme':'dark', 'flowchart':{'curve':'basis'}}}%%
flowchart LR

%% ═══════════════════════════════════════════════════════
%% PALETA DE ESTILOS
%% Mesma semântica do original — cada classe = categoria
%% ═══════════════════════════════════════════════════════

classDef user fill:#21262d, stroke:#8b949e, stroke-width:2px, color:#c9d1d9
classDef bot fill:#1f6feb, stroke:#58a6ff, stroke-width:3px, color:#ffffff
classDef formatter fill:#0d419d, stroke:#79c0ff, stroke-width:3px, color:#ffffff
classDef lib fill:#388bfd, stroke:#a5d6ff, stroke-width:2px, color:#ffffff
classDef api fill:#238636, stroke:#2ea043, stroke-width:3px, color:#ffffff
classDef db fill:#da3633, stroke:#ff7b72, stroke-width:3px, color:#ffffff
classDef external fill:#161b22, stroke:#6e7681, stroke-width:2px, color:#8b949e, stroke-dasharray:5 5
classDef telegrm fill:#0088cc, stroke:#58a6ff, stroke-width:2px, color:#ffffff, stroke-dasharray:5 5
classDef file fill:#d29922, stroke:#e3b341, stroke-width:2px, color:#000000
classDef async fill:#8957e5, stroke:#d2a8ff, stroke-width:2px, color:#ffffff
classDef layer fill:#161b22, stroke:#30363d, stroke-width:1px, color:#8b949e

%% ─── Atores externos (coluna da esquerda) ──────────────
User(["👨‍👩‍👧 Família Steam"]):::user
Telegram((("💬 Telegram API"))):::telegrm

%% ─── Núcleo da aplicação ────────────────────────────────
subgraph APP["🖥️  Servidor RatBot — Arquitetura Assíncrona"]
    subgraph APRESENTACAO["✉️  Camada de Apresentação"]
        direction TB
        Formatter["✉️ formatters.py"]:::formatter
        Telegramify["📝 telegramify-markdown<br/>(Markdown → MessageEntity)"]:::lib
    end
    subgraph ORQUESTRACAO["🧠  Camada de Orquestração"]
        direction TB
        Manager{"🧠 bot.py<br/>(Gerente / Event Loop)"}:::bot
        Paralelismo["⚡ asyncio.gather<br/>(return_exceptions=True)"]:::async
    end
    subgraph DADOS["🗄️  Camada de Dados"]
        direction TB
        Messenger["🌐 api.py<br/>(aiohttp)"]:::api
        Archivist["💾 database.py<br/>(aiofiles)"]:::db
    end
end

%% ─── Recursos e APIs (coluna da direita) ────────────────
Lock(("🔒 asyncio.Lock")):::file
Arquivo[/"📁 database.json"\]:::file
Steam((("🎮 Steam API"))):::external
ITAD((("🏷️ ITAD API"))):::external

%% ─── FLUXO DE ENTRADA ───────────────────────────────────
User  <-->|"Comandos /<br/>Respostas"| Telegram
Telegram  <-->|"Polling Async<br/>(recebe Update)"| Manager

%% ─── FLUXO DE SAÍDA ─────────────────────────────────────
Manager  -->|"Delega<br/>formatação"| Formatter
Formatter  -->|"Converte MD<br/>→ entities"| Telegramify
Formatter  -->|"reply_text / reply_photo<br/>(sem parse_mode)"| Telegram

%% ─── BUSCA DE DADOS (paralela) ──────────────────────────
Manager  -->|"Dispara em<br/>paralelo"| Paralelismo
Paralelismo  -.->|"Non-blocking"| Messenger
Messenger  -->|"Sessão aiohttp"| Steam
Messenger  -->|"Sessão aiohttp<br/>(reaproveitada)"| ITAD

%% ─── PERSISTÊNCIA ────────────────────────────────────────
Manager  -->|"Salvar /<br/>Consultar"| Archivist
Archivist  -.->|"Aguarda Lock"| Lock
Lock  -.->|"I/O via aiofiles"| Arquivo

%% ─── ESTILOS DE CAMADAS E CONTAINER ─────────────────────
style APP fill:transparent, stroke:#30363d, stroke-width:2px, stroke-dasharray:15 8, color:#8b949e
style APRESENTACAO fill:#0d1117, stroke:#79c0ff, stroke-width:1px, color:#79c0ff
style ORQUESTRACAO fill:#0d1117, stroke:#58a6ff, stroke-width:1px, color:#58a6ff
style DADOS fill:#0d1117, stroke:#2ea043, stroke-width:1px, color:#2ea043

%% ─── LEGENDA ─────────────────────────────────────────────
    subgraph LEGENDA["🗺️  Legenda"]
        direction LR
        LA["Módulo<br/>interno"]:::bot
        LB(("Recurso<br/>compartilhado")):::file
        LC((("Serviço<br/>externo"))):::external
        LD["Camada de<br/>Apresentação"]:::formatter
        LE["Camada de<br/>Dados"]:::api
    end

%% ─── CORES POR FLUXO ─────────────────────────────────────
%% Índices na ordem de declaração das arestas acima:
%% 0-1   → Entrada (User↔Telegram↔Manager)    → azul
%% 2-4   → Saída (Manager→Formatter→Telegram)  → verde
%% 5-8   → Dados (gather→api→Steam/ITAD)       → roxo
%% 9-11  → Persistência (→Archivist→Lock→json) → laranja

linkStyle 0,1 stroke:#58a6ff,stroke-width:2.5px
linkStyle 2,3,4 stroke:#2ea043,stroke-width:2.5px
linkStyle 5,6,7,8 stroke:#8957e5,stroke-width:2px,stroke-dasharray:6
linkStyle 9,10,11 stroke:#d29922,stroke-width:2px,stroke-dasharray:4
```

## Configuração Inicial

1. **Instale as dependências** (só precisa fazer isso UMA VEZ):
   Abra o terminal na pasta do projeto e rode:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure suas chaves no `.env`**:
   Crie um arquivo `.env` na raiz do projeto com o seguinte conteúdo:
   ```env
   BOT_TOKEN=seu_token_do_telegram_aqui
   ITAD_API_KEY=sua_chave_do_isthereanydeal_aqui
   ```

## Executando o Projeto

### 1. Iniciar o bot
```bash
python bot.py
```
Você verá a mensagem `✅ Bot is running!`. Para parar, pressione **Ctrl+C**.

### 2. Rodar os testes
Garantimos a qualidade do código com 121 testes unitários. Para rodá-los:
```bash
# Rodar todos os testes
python -m pytest tests/ -v

# Rodar com relatório de cobertura
python -m pytest tests/ -v --cov=. --cov-report=term-missing
```

### 3. Benchmarks de performance
```bash
# Benchmark do database (I/O, lookup, scan)
python tests/benchmarks/bench_database.py

# Benchmark da API (overhead de processamento)
python tests/benchmarks/bench_api.py
```

Consulte `docs/performance_analysis.md` para análise detalhada de Big-O, resultados e recomendações.

## Comandos do Bot

| Comando | Status | Descrição |
|---------|--------|-----------|
| `/start` | ✅ Pronto | Mensagem de boas-vindas |
| `/help` | ✅ Pronto | Lista de comandos detalhada |
| `/add [URL]` | ✅ Pronto | Adiciona jogo recebendo dados da Steam e ITAD |
| `/want [ID\|URL]` | ✅ Pronto | Registra interesse e calcula divisão do custo |
| `/list` | ✅ Pronto | Lista formatada de todos os jogos com preços e loja do melhor deal |
| `/game [ID]` | ✅ Pronto | Detalhes completos de um jogo: preços, status, interessados e racha |
| `/delete [ID]` | 🚧 Em breve | Remove um jogo específico da lista |
| `/unwant [ID]` | 🚧 Em breve | Sai do racha de um jogo específico informando apenas o AppID |
| `/update [ID]` | 🚧 Em breve | Atualiza os preços atuais de um jogo específico |
| `/all2date` | 🚧 Em breve | Atualiza os preços de todos os jogos na base de dados iterativamente |

