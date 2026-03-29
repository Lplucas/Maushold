# ADR-001: Decisões Arquiteturais — Migração Assíncrona (Sprint 2)

**Data:** 2026-03-29  
**Status:** Aceito  
**Autor(es):** Antigravity & Lucas  

## Contexto
Durante a Sprint 2, o objetivo primário foi refatorar todo o código base (I/O de rede e arquivos) para funcionar de forma 100% não bloqueante (async/await), visando que o loop de eventos principal do `python-telegram-bot` nunca engasgasse ao servir múltiplos usuários (e preparando o app para implantação no Cloud Run / VPS).

Várias escolhas técnicas precisaram ser equilibradas no caminho: overhead de código vs precisão acadêmica vs simplicidade de manutenção futura.

## Decisões Tomadas

### 1. Criação de `ClientSession` por chamada vs Sessão Global Única
Na função `get_steam_game_info` e `_get_itad_uuid`, decidimos instanciar um novo `aiohttp.ClientSession` a cada chamada da função (através do pattern `async with aiohttp.ClientSession() as session`).
* **Sessão Global seria mais rápida?** Sim, o pool de conexões TCP seria reutilizado, poupando a latência do handshake.
* **A justificativa:** Uma Sessão Global única compartilhada em nível de módulo introduz complexidade no ciclo de vida da aplicação (preciso lembrar de fechar a sessão ao finalizar o bot, e preciso lidar com o fato de que a sessão não pode ser criada "fora do event loop"). Como estamos trabalhando com requests espaçados no tempo por causa da interação orgânica no Telegram, o overhead do TCP handshake extra é negligenciável (alguns ms) frente às dificuldades arquiteturais que uma Sessão Global traria nessa sprint.
* **A exceção (`get_itad_prices`):** A única vez em que reaproveitamos a sessão explicitamente foi em `get_itad_prices()`, porque ele faz DUAS requisições *na mesma função* ao mesmo servidor (ITAD deals API, e em seguida ITAD history API). Nela, reaproveitar a sessão fazia todo sentido e exigia 0 complexidade no ciclo de vida (ela é criada e destruída no escopo da função). A Sprint 4 (PriceService) avaliará pooling mais elegante.

### 2. `extract_app_id_from_url` permaneceu Síncrono (sync)
Mesmo com tudo ao redor virando `async def`, escolhemos deixar a função de regex estritamente como `def` síncrono.
* **A justificativa:** Não existe nenhuma operação de I/O bloqueante (arquivos, redes, conexões com banco) dentro desta função. Fazer match de expressão regular em uma string minúscula é uma operação atômica de CPU na qual event loops não conseguem aplicar paralelismo (não existe bloqueio do qual ceder o controle (`await`)). Transfomar em `async def` seria over-engineering apenas por "padronização visual", introduzindo overhead de agendamento de coroutine no event loop do asyncio à toa. E manter síncrona facilita nos testes unitários, que não precisaram ser refatorados inteiros.

### 3. Falhas Moles via `return_exceptions=True` no Paralelismo
Em `_add_game_to_db` de `bot.py`, chamamos a API da Steam e a API da ITAD no mesmo segundo usando o paralelismo do `asyncio.gather(steam_coro, itad_coro, return_exceptions=True)`.
* **A justificativa:** Usado por padrão, se uma exception explodisse na request do ITAD (ex.: timeout, 404, erro de rate limit), o `gather` seria interrompido inteiro e o erro propagaria destruindo inclusive a busca já completada com sucesso da Steam, impedindo o jogo de ser incluído no banco. Ao forçarmos o `return_exceptions=True`, blindamos as duas pipelines: se o ITAD der timeout, o game será adicionado ao banco normalmente, com preços atuais da Steam, e seu campo de de deal com `best_deal_price=-1.0` (vazio). O bot será robusto e autônomo na falha de serviços de terceiros.

### 4. Troca da dependência `requests` por `aiohttp` totalmente limpa
A decisão aqui era se manteríamos `requests` para funções auxiliares, como buscar a capa do jogo por exemplo (no futuro). Decidiu-se retirar sumariamente. 
* **A justificativa:** Evitar que código novo seja introduzido sorrateiramente sendo bloqueante. Sem `requests` no `requirements.txt`, há a garantia que todo novo fetch de internet num Pull Request forçará o modelo ou desenvolvedor a pensar através do prima `async`/`await` em `aiohttp`, bloqueando deslizes arquiteturais. 

### 5. `logger.info` no lugar de `print()` + Problemas com Emojis
Ao inicializar o bot, utilizávamos `print("✅ Bot is running")`. Percebeu-se que em sistemas Windows padrão, o charset CP1252 era ativado gerando o crash `UnicodeDecodeError` por causa dos emojis e parando a execução antes mesmo de iniciar.
* **A justificativa:** A remoção dos emojis estritamente nos prints de incialização do servidor, enquanto continuaram liberados para os envios de Telegram e a migração de loggers estruturados (`logging.getLogger()`) garante uma subida blindada contra problemas de encoding de SO sem perder a ludicidade que o app requer no Front-End do Telegram.

--- 
*Notas preservadas para guia futuro sobre como escalar event loop requests e serviços na Sprint 4.*
