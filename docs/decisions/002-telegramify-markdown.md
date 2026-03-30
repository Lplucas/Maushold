# ADR-002: Migração de `parse_mode="Markdown"` para `telegramify-markdown` (Entities)

**Data:** 2026-03-30  
**Status:** Aceito  
**Autor(es):** Antigravity & Lucas  

## Contexto

O bot utilizava `parse_mode="Markdown"` (parser legado do Telegram) para formatar todas as mensagens enviadas. Este parser é extremamente frágil: qualquer caractere especial (`*`, `_`, `` ` ``, `[`, `]`) presente em dados dinâmicos (nomes de jogos, lojas, usernames) causa `BadRequest: Can't parse entities`, silenciosamente quebrando comandos como `/list` e `/game`.

O problema se manifestou gradualmente conforme jogos com nomes complexos foram adicionados ao banco (ex: jogos com underscores como `DEATH_STRANDING`, lojas com nomes como `Games_Planet`).

## Decisões Tomadas

### 1. `telegramify-markdown` como motor de conversão (em vez de escape manual ou MarkdownV2)

Três abordagens foram avaliadas:

| Abordagem | Prós | Contras |
|---|---|---|
| **Escape manual** | Zero dependência | Frágil, error-prone, cada char especial precisa de tratamento |
| **MarkdownV2** (nativo Telegram) | Suportado oficialmente | Exige escape de ~18 caracteres, sintaxe não-padrão |
| **`telegramify-markdown`** ✅ | Markdown padrão (GFM), converte para entities | Dependência externa |

* **Escolha:** `telegramify-markdown==1.1.1` — converte Markdown padrão (GitHub-flavored) para `(texto_limpo, list[MessageEntity])`, eliminando completamente a necessidade de `parse_mode`. O Telegram aplica a formatação via entities nativas, que são imunes a injeção de caracteres especiais.
* **Justificativa:** A biblioteca tem manutenção ativa, suporta todas as features do Telegram (bold, italic, code, spoiler, blockquote, links), e permite escrever Markdown natural sem preocupação com escaping. O custo da dependência é mínimo comparado ao ganho de robustez.

### 2. Criação do módulo `formatters.py` (em vez de inline em `bot.py`)

* **Escolha:** Toda lógica de formatação e envio de mensagens foi extraída de `bot.py` para um módulo dedicado `formatters.py`.
* **Justificativa:** Separação de responsabilidades — `bot.py` atua exclusivamente como orquestrador de comandos (recebe input, chama serviços, delega apresentação). `formatters.py` é a única fonte de verdade para a UI textual do bot. Isso permite testar formatação isoladamente sem mocks de Telegram.

### 3. Encapsulamento de envio em `send_md()`, `edit_md()`, `send_photo_md()`

* **Escolha:** Três helpers async que encapsulam o padrão `convert() → reply_text(text, entities=[...])`.
* **Justificativa:** Nenhum handler precisa saber como a conversão funciona internamente. Se trocarmos a biblioteca no futuro, apenas esses 3 helpers mudam. Cada helper inclui fallback gracioso: se `convert()` falhar, o texto é enviado sem formatação (melhor que crash).

### 4. `_format_price()` com formato BRL localizado (`R$ 59,90`)

* **Escolha:** Mudança de `R$ 59.90` (formato US) para `R$ 59,90` (formato BRL real), e tratamento de `0.0` como `Grátis 🎉`.
* **Justificativa:** O público do bot é brasileiro. A formatação anterior usava ponto decimal por conveniência de implementação, mas era confusa para o usuário final. O preço zero agora tem tratamento semântico explícito.

### 5. Features visuais integradas na migração (não em sprint separada)

* **Escolha:** 5 features visuais (URLs ocultas, blockquotes, spoilers, monospace, banners) foram implementadas junto com a correção do bug, não em uma sprint posterior.
* **Justificativa:** Todas dependem de `MessageEntity` para funcionar corretamente — a mesma infra que a migração introduz. Separá-las significaria tocar nos mesmos arquivos duas vezes com risco de regressão. O custo incremental foi mínimo (a infra já estava sendo construída).

### 6. Paginação via `split_entities()` (em vez de `len()` manual)

* **Escolha:** O `/list` agora usa `split_entities()` da biblioteca para dividir mensagens longas, respeitando o limite de 4096 UTF-16 code units do Telegram.
* **Justificativa:** `len()` do Python conta code points Unicode, não code units UTF-16. Emojis como 🔥 contam como 1 em Python mas 2 no Telegram. A função anterior podia gerar mensagens que excediam o limite real, causando truncamento silencioso.

## Impacto

- `bot.py`: Zero ocorrências de `parse_mode` funcional (apenas 1 em comentário explicativo).
- `formatters.py`: 470 linhas, 100% documentado com docstrings.
- Cobertura de testes: 121/121 passando (56 novos em `test_formatters.py`).
- O bot é agora imune a injeção de caracteres especiais via dados dinâmicos.

## Riscos Residuais

1. **Dependência externa:** Se `telegramify-markdown` for descontinuada, os 3 helpers de envio precisarão ser reimplementados. Risco baixo — a API de entities do Telegram é estável.
2. **Caption de foto > 1024 chars:** Se um jogo tiver nome extremamente longo, o caption pode exceder o limite. Mitigação futura: truncar com `...` em `build_game_summary_caption()`.

---
*Decisão registrada como parte do hotfix v0.7.2.*
