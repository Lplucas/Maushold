# RatFamilyBot 🐀

Um bot para o Telegram que substitui a planilha compartilhada para racharem jogos da Steam!

## Estrutura do Projeto
```text
RatBot/
├── bot.py                 # Arquivo principal — conecta ao Telegram, recebe comandos e orquestra chamadas assíncronas
├── api.py                 # Comunicação externa (Steam API e ITAD API) via requisições aiohttp (Non-blocking)
├── database.py            # Toda a lógica de leitura/escrita do banco de JSON de forma assíncrona com aiofiles
├── database.json          # Criado automaticamente na primeira execução
│
├── tests/                 # Testes unitários (pytest) — 65 testes
│   ├── conftest.py        # Fixtures reutilizáveis (mock_update, mock_context)
│   ├── test_api.py        # 22 testes — URLs, Steam API, ITAD, erros, mock assíncrono
│   ├── test_bot.py        # 20 testes — todos os comandos + helpers
│   ├── test_database.py   # 17 testes — CRUD, edge cases, resiliência
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
graph TD
    %% Estilos Globais (Otimizados com a Paleta Nativa do GitHub Dark Mode)
    classDef user fill:#21262d,stroke:#8b949e,stroke-width:2px,color:#c9d1d9,rx:20,ry:20
    classDef bot fill:#1f6feb,stroke:#58a6ff,stroke-width:3px,color:#ffffff,rx:20,ry:20
    classDef api fill:#238636,stroke:#2ea043,stroke-width:3px,color:#ffffff,rx:20,ry:20
    classDef db fill:#da3633,stroke:#ff7b72,stroke-width:3px,color:#ffffff,rx:20,ry:20
    classDef external fill:#161b22,stroke:#6e7681,stroke-width:2px,color:#8b949e,stroke-dasharray: 5 5,rx:10,ry:10
    classDef telegrm fill:#0088cc,stroke:#58a6ff,stroke-width:2px,color:#ffffff,stroke-dasharray: 5 5,rx:10,ry:10
    classDef file fill:#d29922,stroke:#e3b341,stroke-width:2px,color:#000000
    classDef async fill:#8957e5,stroke:#d2a8ff,stroke-width:2px,color:#ffffff,rx:5,ry:5
    classDef spacer fill:none,stroke:none,color:transparent

    %% Atores e Sistemas
    User(👨‍👩‍👧 Família Steam):::user
    Telegram(((💬 API do Telegram))):::telegrm

    %% Nódulos do Nosso App
    subgraph APP["Servidor do RatBot (Arquitetura 100% Assíncrona)"]
        Space[ ]:::spacer
        Manager{"🧠 bot.py<br>(Gerente / Event Loop)"}:::bot
        Messenger["🌐 api.py<br>(Mensageiro / aiohttp)"]:::api
        Archivist["💾 database.py<br>(Arquivista / aiofiles)"]:::db
        Paralelismo["⚡ asyncio.gather<br>(Despachante Paralelo)"]:::async
        Space ~~~ Manager
    end

    %% Recursos Locais
    Lock((🔒 asyncio.Lock)):::file
    Arquivo[/"📁 database.json"\]:::file

    %% Recursos Externos
    Steam(((🎮 Steam API))):::external
    ITAD(((🏷️ ITAD API))):::external

    %% Conexões do Usuário
    User <-->|"Manda /comandos<br>Recebe Mensagens"| Telegram
    Telegram <-->|Polling Async| Manager

    %% Conexões Internas do App
    Manager -->|Dispara múltiplas buscas| Paralelismo
    Paralelismo -.->|"Busca de forma simultânea<br>(Non-blocking)"| Messenger
    Manager -->|Pede para salvar ou consultar| Archivist

    %% Conexões do Mensageiro (API)
    Messenger -->|Sessão aiohttp| Steam
    Messenger -->|"Sessão aiohttp<br>(Conexão reaproveitada)"| ITAD

    %% Conexões do Arquivista (DB)
    Archivist -.->|Aguarda Lock assíncrono| Lock
    Lock -.->|"Abre, Lê, Salva, Fecha<br>(I/O via aiofiles)"| Arquivo

    %% Estilo do Servidor (Fundo transparente, borda padrão GitHub de demarcação)
    style APP fill:transparent,stroke:#30363d,stroke-width:2px,stroke-dasharray: 15 10 8 4,color:#8b949e
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
Garantimos a qualidade do código com 55 testes unitários. Para rodá-los:
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

