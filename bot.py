# =============================================================================
# bot.py — Ponto de entrada do RatFamilyBot
# =============================================================================
# Controla toda a interação com o Telegram: recebe comandos, chama api.py
# para dados de preço (Steam + ITAD via aiohttp) e database.py para
# persistência (via aiofiles). Todas as chamadas externas são assíncronas.
#
# FEATURES:
#   /start    → Mensagem de boas-vindas
#   /help     → Lista de todos os comandos
#   /add      → Adiciona jogo via URL da Steam
#   /want     → Registra interesse em rachar um jogo
#   /list     → Lista todos os jogos com preços e interessados
#   /game     → Detalhes de um jogo específico por AppID
#   /delete   → Remove um jogo do banco de dados
#   /unwant   → Remove interesse de um jogo
#   /all2date → Atualiza preços de todos os jogos
#
# ARQUITETURA ASSÍNCRONA:
#   - api.py: HTTP via aiohttp (não-bloqueante)
#   - database.py: I/O via aiofiles (não-bloqueante)
#   - _add_game_to_db(): asyncio.gather() para Steam+ITAD em paralelo
# =============================================================================

import logging          # Python's built-in tool for printing useful log messages
import asyncio           # asyncio.gather() for parallel async calls
import os               # Used to read environment variables (our bot token)
from dotenv import load_dotenv  # Reads our .env file into environment variables

# Our own modules (files we wrote):
# - api.py handles ALL network calls (Steam, ITAD) via aiohttp
# - database.py handles ALL file reads/writes via aiofiles
# - formatters.py handles ALL message formatting and sending (Markdown → entities)
import api
import database
import formatters

# These are the core classes we need from the python-telegram-bot library.
# - Application: The main bot object that connects everything together.
# - CommandHandler: Tells the bot "when you see /this_command, run this function".
# - ContextTypes: Gives us access to helper objects inside our command functions.
# - Update: Represents an incoming message or event from Telegram.
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


# =============================================================================
# SETUP
# =============================================================================

# Load the variables from our .env file into the system environment.
# After this line, os.getenv("BOT_TOKEN") will return our actual token.
load_dotenv()

# Configure logging so the bot prints helpful messages to the terminal.
# This is like turning on the "debug mode" for our bot.
# FORMAT: shows the time, the log level (INFO/ERROR), and the message.
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO  # INFO shows general activity; use DEBUG for more detail
)

# Get a logger for this specific file. Good practice for larger projects.
logger = logging.getLogger(__name__)


# =============================================================================
# COMMAND HANDLERS
# Each function below handles one specific bot command.
# They all have the same two arguments:
#   - update: Contains ALL info about the incoming message (who sent it, text, etc.)
#   - context: Contains bot utilities and any data we want to pass between handlers.
# They are all "async" because Telegram communication is asynchronous — the bot
# can receive many messages at once without waiting for each one to finish.
# =============================================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the /start command.
    Triggered when a user first starts a chat with the bot OR types /start.
    Its job is to give a friendly greeting and explain what the bot does.
    """
    user_first_name = update.effective_user.first_name

    welcome_message = (
        f"🐀 Olá, {user_first_name}! Bem-vindo ao **RatFamilyBot**!\n\n"
        "Eu ajudo a galera a racharem o custo de jogos da Steam. "
        "Nada de planilha, tudo aqui no chat!\n\n"
        "📋 **O que eu faço:**\n"
        "  • Busco o preço atual e o menor preço histórico de jogos\n"
        "  • Registro quem quer participar do racha\n"
        "  • Calculo o valor por pessoa automaticamente\n\n"
        "⚙️ **Comandos disponíveis:**\n"
        "  /add `[URL da Steam]` — Adicionar um jogo\n"
        "  /want `[AppID ou Nome]` — Quero participar do racha!\n"
        "  /list — Ver todos os jogos e preços\n"
        "  /help — Mostra esta mensagem novamente\n\n"
        "Para começar, tente: `/add https://store.steampowered.com/app/1091500`"
    )

    # Envia via entities (sem parse_mode) — imune a caracteres especiais
    await formatters.send_md(update.message, welcome_message)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the /help command.
    Shows the user a clean list of all available commands and how to use them.
    """
    help_message = (
        "🎁 **RatFamilyBot — Comandos disponíveis**\n\n"
        "🔹 `/add [URL da Steam]`\n"
        "   Adiciona um jogo à lista. Ex:\n"
        "   `/add https://store.steampowered.com/app/1091500/`\n\n"
        "🔹 `/want [AppID]`\n"
        "   Entra no racha de um jogo. O AppID aparece no `/add` e no `/list`. Ex:\n"
        "   `/want 1091500`\n\n"
        "🔹 `/list`\n"
        "   Mostra todos os jogos com preços, status e valor por pessoa.\n\n"
        "🔹 `/game [AppID]`\n"
        "   Detalha um jogo específico com lista de interessados.\n\n"
        "🔹 `/start` ou `/help`\n"
        "   Mostra esta mensagem de ajuda.\n\n"
        "💡 **Dica:** Use `/add` com a URL completa da Steam para garantir que o jogo seja encontrado!"
    )

    await formatters.send_md(update.message, help_message)


# =============================================================================
# /add COMMAND — Step 2 Implementation (ITAD Edition)
# Flow: Validate URL → Parse AppID → Fetch name (Steam) →
#        Fetch prices + history (ITAD, in BRL) → Save to DB → Confirm
# =============================================================================

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the /add [Steam URL] command.

    Delegates the heavy lifting (API calls + DB save) to _add_game_to_db(),
    which is shared with want_command(). This eliminates code duplication
    and ensures consistent behavior (DRY principle).

    Edge cases handled:
      - No URL provided → usage instructions
      - Non-Steam URL → error with example
      - Steam API failure → abort with message
      - ITAD unavailable → sentinel values (-1.0) saved transparently
      - Game already in database → duplicate warning
    """
    # --- STEP 1: Validate that the user provided a URL ---
    if not context.args:
        await formatters.send_md(
            update.message,
            "⚠️ Você esqueceu a URL! Use assim:\n"
            "`/add https://store.steampowered.com/app/1091500/`"
        )
        return

    raw_input = context.args[0]

    # --- STEP 2: Extract the AppID from the URL ---
    app_id = api.extract_app_id_from_url(raw_input)

    if not app_id:
        await formatters.send_md(
            update.message,
            "❌ Link inválido! Precisa ser uma URL da Steam Store. Exemplo:\n"
            "`/add https://store.steampowered.com/app/1091500/`"
        )
        return

    # --- STEP 3: Loading message (API calls take time) ---
    loading_message = await update.message.reply_text(
        f"🔍 Buscando informações para o AppID {app_id}..."
    )

    # --- STEP 4: Delegate to shared helper ---
    # _add_game_to_db() handles: Steam API → ITAD API → database.add_game()
    # This is the SINGLE source of truth for the "fetch + save" flow.
    # Both /add and /want use the same helper, avoiding duplicate logic.
    add_result = await _add_game_to_db(app_id)

    # --- STEP 5: Handle Steam API failure ---
    if add_result["status"] == "steam_error":
        await formatters.edit_md(
            loading_message,
            f"❌ Não encontrei nenhum jogo com AppID `{app_id}` na Steam.\n"
            "Verifique se o link está correto."
        )
        return

    game_name = add_result["game_name"]

    # --- STEP 6: Handle duplicate ---
    if add_result["status"] == "duplicate":
        await formatters.edit_md(
            loading_message,
            f"⚠️ **{game_name}** já está na nossa lista!\n"
            "Use `/list` para ver todos os jogos."
        )
        return

    # --- STEP 7: Build confirmation with banner + full price details ---
    game_data = await database.get_game_by_id(app_id)

    # Deletar a mensagem de loading — vamos substituir por banner
    try:
        await loading_message.delete()
    except Exception:
        pass  # Se falhar, não é crítico

    caption = formatters.build_game_summary_caption(game_data, app_id)
    caption += f"\n\nUse `/want {app_id}` para entrar no racha!"
    banner_url = formatters.steam_banner_url(app_id)

    await formatters.send_photo_md(update.message, banner_url, caption)


# =============================================================================
# SHARED HELPER — Fetch data from Steam + ITAD and save to database
# =============================================================================
# This helper is called by BOTH add_command and want_command (when a Steam URL
# is passed directly to /want). Extracting it avoids copy-pasting the same
# 30 lines of API calls in two places — a fundamental DRY principle.
#
# DRY = "Don't Repeat Yourself": if two places do the same thing, make a function.
# =============================================================================

async def _add_game_to_db(app_id: str) -> dict:
    """
    Internal helper: fetches game data from Steam + ITAD and saves to DB.

    Usa asyncio.gather() para buscar Steam e ITAD em PARALELO, reduzindo
    o tempo total de ~2 requests sequenciais para ~1 round-trip (o mais lento).

    return_exceptions=True: se uma das chamadas falhar, a outra continua
    normalmente — o resultado da chamada que falhou é retornado como uma
    instância de Exception em vez de propagar a exceção.

    Used by add_command and want_command (Steam URL path).

    Returns a dict with the result of the operation:
      {
        "status": "added" | "duplicate" | "steam_error" | "ok",
        "game_name": str | None,
        "current_price": float,
      }
    """
    # --- Chamadas PARALELAS via asyncio.gather() ---
    # Antes (sequencial): ~2s total (1s Steam + 1s ITAD)
    # Depois (paralelo):  ~1s total (ambas rodam ao mesmo tempo)
    steam_info, itad_data = await asyncio.gather(
        api.get_steam_game_info(app_id),
        api.get_itad_prices(app_id),
        return_exceptions=True,  # Falha em uma não cancela a outra
    )

    # Se gather() capturou uma exceção, o resultado é a exceção em vez do dict.
    # Tratamos qualquer Exception como se a API tivesse retornado None.
    if isinstance(steam_info, Exception) or steam_info is None:
        return {"status": "steam_error", "game_name": None, "current_price": -1.0}

    game_name = steam_info["name"]
    current_price = steam_info["current_price"]

    # ITAD é optional — o bot funciona mesmo sem dados de deal/histórico
    if isinstance(itad_data, Exception) or itad_data is None:
        best_deal_price = -1.0
        best_deal_shop  = ""
        historical_low  = -1.0
    else:
        best_deal_price = itad_data["best_deal_price"]
        best_deal_shop  = itad_data.get("best_deal_shop", "")
        historical_low  = itad_data["historical_low"]

    was_added = await database.add_game(
        app_id=app_id,
        name=game_name,
        current_price=current_price,
        best_deal_price=best_deal_price,
        best_deal_shop=best_deal_shop,
        historical_low=historical_low
    )

    status = "added" if was_added else "duplicate"
    return {"status": status, "game_name": game_name, "current_price": current_price}


# =============================================================================
# /want COMMAND — Step 3 Implementation
# Supports two input modes:
#   1. Steam URL  → auto-add (if needed) + register interest
#   2. Numeric AppID → register interest only (must already be in DB)
# =============================================================================

async def want_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the /want command. Accepts either a Steam URL or a numeric AppID.

    PATH A — Steam URL (e.g. /want https://store.steampowered.com/app/1091500/)
      The bot acts as if the user ran /add followed by /want:
        1. Fetches game data from Steam + ITAD
        2. Saves to DB (skips if already there)
        3. Registers the user's interest

    PATH B — Numeric AppID (e.g. /want 1091500)
      The game MUST already be in the DB. If not, the bot explains
      how to add it first (via /add or via /want with the Steam URL).

    Edge cases handled:
      - No argument → usage instructions
      - Non-URL, non-numeric text → helpful error
      - Steam API failure → abort with message
      - Duplicate interest → friendly notification
      - User has no @username → first_name fallback
    """
    # --- STEP 1: Validate that something was provided ---
    if not context.args:
        await formatters.send_md(
            update.message,
            "⚠️ Você precisa informar o jogo! Você pode usar:\n\n"
            "🔗 **Link da Steam** (adiciona e entra no racha automaticamente):\n"
            "`/want https://store.steampowered.com/app/1091500/`\n\n"
            "🔢 **AppID** (se o jogo já foi adicionado com `/add`):\n"
            "`/want 1091500`\n\n"
            "*O AppID aparece quando você usa `/add` ou `/list`.*"
        )
        return

    raw_input = context.args[0].strip()

    # --- STEP 2: Identify the user (same for both paths) ---
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name or "Alguém sem nome"

    # --- PATH ROUTING: decide which path to take ---
    # We detect a Steam URL by looking for the "/app/" pattern.
    # api.extract_app_id_from_url() returns None if it's not a valid Steam URL.
    app_id_from_url = api.extract_app_id_from_url(raw_input)

    if app_id_from_url:
        # =========================================================
        # PATH A: Steam URL detected
        # If game is already in DB → skip APIs, just inform + proceed
        # If game is NOT in DB → fetch from Steam+ITAD, add it, proceed
        # =========================================================
        app_id = app_id_from_url

        existing_game = await database.get_game_by_id(app_id)

        if existing_game:
            await formatters.send_md(
                update.message,
                f"ℹ️ **{existing_game['name']}** já está na lista!\n"
                "Registrando seu interesse..."
            )
        else:
            loading_message = await update.message.reply_text(
                "🔍 Buscando o jogo na Steam..."
            )

            add_result = await _add_game_to_db(app_id)

            if add_result["status"] == "steam_error":
                await formatters.edit_md(
                    loading_message,
                    f"❌ Não encontrei nenhum jogo com AppID `{app_id}` na Steam.\n"
                    "Verifique se o link está correto."
                )
                return

            await formatters.edit_md(
                loading_message,
                f"✅ **{add_result['game_name']}** adicionado à lista!\n"
                "Registrando seu interesse..."
            )

    elif raw_input.isdigit():
        # =========================================================
        # PATH B: Numeric AppID → want only
        # =========================================================
        app_id = raw_input

    else:
        # =========================================================
        # PATH C: Invalid input — neither URL nor number
        # =========================================================
        await formatters.send_md(
            update.message,
            "❌ Entrada inválida! Use um link da Steam ou um AppID numérico:\n\n"
            "🔗 `/want https://store.steampowered.com/app/1091500/`\n"
            "🔢 `/want 1091500`"
        )
        return

    # --- STEP 3: Register the user's interest ---
    result = await database.add_interested_user(
        app_id=app_id,
        user_id=user_id,
        username=username
    )

    # --- STEP 4: Reply based on the result ---

    if result == "not_found":
        await formatters.send_md(
            update.message,
            f"❌ O jogo com AppID `{app_id}` não está na nossa lista.\n\n"
            "Para adicioná-lo, você pode:\n"
            "• Usar `/add [URL da Steam]`\n"
            "• Ou enviar o link direto no `/want`:\n"
            "  `/want https://store.steampowered.com/app/1091500/`"
        )
        return

    if result == "duplicate":
        game = await database.get_game_by_id(app_id)
        game_name = game["name"] if game else app_id
        await formatters.send_md(
            update.message,
            f"⚠️ Você já está no racha de **{game_name}**!\n"
            "Aguarda seus parceiros entrarem. 😄"
        )
        return

    # result == "added" — success!
    game = await database.get_game_by_id(app_id)
    if not game:
        await formatters.send_md(
            update.message,
            f"✅ Interesse registrado no jogo `{app_id}`!"
        )
        return

    game_name = game["name"]
    interested_users = game["interested_users"]
    total = len(interested_users)

    # Usar formatters para lista inline e preço por pessoa
    people_str, per_person_str = formatters.build_interests_inline(game)

    # Spoiler no preço por pessoa (UX Feature 3)
    if per_person_str != "—":
        price_display = f"||{per_person_str} por pessoa||"
    else:
        price_display = "Indisponível"

    await formatters.send_md(
        update.message,
        f"✅ **{username}** entrou no racha de **{game_name}**!\n\n"
        f"👥 **Interessados ({total}):** {people_str}\n"
        f"💸 **Preço por pessoa:** {price_display}\n\n"
        "*Quanto mais gente entrar, mais barato fica!* 😎"
    )


# NOTE: _format_price() and _get_status_emoji() have been migrated to formatters.py.
# They remain importable for tests via: formatters._format_price, formatters._get_status_emoji


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the /list command. Shows all tracked games with:
      - Status emoji (🔥 / ✅ / ❌)
      - Steam price (linked), best current deal, historical low
      - Interested people inline and price per person

    Uses formatters.build_list_block() for each game and split_entities()
    for proper UTF-16 pagination.
    """
    games = await database.get_all_games()

    if not games:
        await formatters.send_md(
            update.message,
            "📭 **A lista está vazia!**\n\n"
            "Nenhum jogo foi adicionado ainda.\n"
            "Use `/add [URL da Steam]` para adicionar o primeiro! 🎮"
        )
        return

    # Build Markdown blocks for each game using formatters
    header = f"🎮 **Lista de jogos ({len(games)} jogo{'s' if len(games) != 1 else ''})**\n\n"
    blocks = []
    for app_id, game in games.items():
        blocks.append(formatters.build_list_block(app_id, game))

    full_md = header + "\n\n".join(blocks)

    # Convert to entities and split respecting Telegram’s 4096 UTF-16 limit
    from telegramify_markdown import convert, split_entities
    text, entities = convert(full_md)
    chunks = list(split_entities(text, entities, max_utf16_len=formatters.TELEGRAM_MESSAGE_LIMIT))

    for chunk_text, chunk_entities in chunks:
        await update.message.reply_text(
            chunk_text,
            entities=[e.to_dict() for e in chunk_entities]
        )


# =============================================================================
# /game COMMAND — Detailed view with banner, blockquote, spoiler, monospace
# =============================================================================

async def game_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the /game [AppID] command. Shows full detail for a specific game.

    Visual features (via formatters):
      - Banner: Steam header.jpg as reply_photo
      - Blockquote: status card (> **...**)
      - Spoiler: price per person hidden until tap
      - Monospace: numbered interested users list
      - Link: game name clickable to Steam Store
    """
    # --- STEP 1: Validate input ---
    if not context.args:
        await formatters.send_md(
            update.message,
            "⚠️ Informe o AppID do jogo! Use assim:\n"
            "`/game 1091500`\n\n"
            "*O AppID aparece quando você usa `/add` ou `/list`.*"
        )
        return

    raw_input = context.args[0].strip()

    # --- STEP 2: Detect Steam URL instead of AppID ---
    extracted = api.extract_app_id_from_url(raw_input)
    if extracted:
        await formatters.send_md(
            update.message,
            f"💡 Parece que você colou um link da Steam!\n"
            f"O comando `/game` usa apenas o AppID. Tente:\n\n"
            f"`/game {extracted}`"
        )
        return

    # --- STEP 3: Validate numeric ---
    if not raw_input.isdigit():
        await formatters.send_md(
            update.message,
            "❌ AppID inválido! O AppID é numérico. Exemplo:\n"
            "`/game 1091500`"
        )
        return

    app_id = raw_input

    # --- STEP 4: Fetch from database ---
    game = await database.get_game_by_id(app_id)

    if not game:
        await formatters.send_md(
            update.message,
            f"❌ Nenhum jogo com AppID `{app_id}` foi encontrado na lista.\n\n"
            "Para adicioná-lo, use:\n"
            f"`/add https://store.steampowered.com/app/{app_id}/`"
        )
        return

    # --- STEP 5: Send banner with summary caption ---
    caption = formatters.build_game_summary_caption(game, app_id)
    banner_url = formatters.steam_banner_url(app_id)
    await formatters.send_photo_md(update.message, banner_url, caption)

    # --- STEP 6: Send interests block with spoiler price ---
    interests_text = formatters.build_game_interests_text(game, app_id)
    await formatters.send_md(update.message, interests_text)




# =============================================================================
# MAIN FUNCTION — Bot Startup
# This is where everything comes together. We build the bot, register all
# commands, and start listening for messages.
# =============================================================================

def main() -> None:
    """
    The main entry point. Builds and starts the Telegram bot.
    """
    # Get the token from the environment variable (loaded from .env by load_dotenv).
    token = os.getenv("BOT_TOKEN")

    # Safety check: if the token is missing, stop immediately with a clear error.
    if not token:
        raise ValueError(
            "BOT_TOKEN not found! Make sure your .env file exists and contains BOT_TOKEN=..."
        )

    # --- BUILD THE APPLICATION ---
    # Application.builder() is the modern way to create a bot in python-telegram-bot v20+.
    # .token(token) passes our secret API key so Telegram knows who we are.
    # .build() finalizes the object.
    logger.info("Starting RatFamilyBot...")
    application = Application.builder().token(token).build()

    # --- REGISTER COMMAND HANDLERS ---
    # This is how we tell the bot: "When someone types /command, call this function."
    # The first argument to CommandHandler is the command name (without the /).
    # The second argument is the Python function to call.

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("add", add_command))    # ✅ Step 2 Done
    application.add_handler(CommandHandler("want", want_command))  # ✅ Step 3 Done
    application.add_handler(CommandHandler("list", list_command))  # 🚧 Step 4
    application.add_handler(CommandHandler("game", game_command))  # 🚧 Step 4 (detail view)

    # --- START POLLING ---
    # run_polling() tells the bot to continuously ask Telegram's servers:
    # "Hey, are there any new messages for me?" every few seconds.
    # This is the simplest approach — no complex server setup needed.
    # The bot will keep running until you press Ctrl+C in the terminal.
    logger.info("Bot is running! Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


# =============================================================================
# ENTRY POINT GUARD
# This "if __name__ == '__main__':" block means: only run main() if this file
# is executed directly (python bot.py), NOT when it's imported by another file.
# It's a Python best practice you'll see in almost every project.
# =============================================================================
if __name__ == "__main__":
    main()
