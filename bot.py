# =============================================================================
# bot.py - The Main Bot File (Steps 1 & 2)
# =============================================================================
# This is the entry point of our bot. Think of it as the "control center".
# It connects to Telegram, listens for commands, and calls functions from
# our other files (api.py, database.py) to do the actual work.
#
# CURRENT FEATURES:
#   - /start  → Welcome message explaining what the bot does
#   - /help   → Lists all available commands
#   - /add    → Add a game via Steam URL (parses URL, fetches data, saves to DB)
#
# COMING SOON (Steps 3-4):
#   - /want   → Express interest in splitting a game's cost
#   - /list   → Show all games with prices and interested users
# =============================================================================

import logging          # Python's built-in tool for printing useful log messages
import os               # Used to read environment variables (our bot token)
from dotenv import load_dotenv  # Reads our .env file into environment variables

# Our own modules (files we wrote):
# - api.py handles ALL network calls (Steam, CheapShark)
# - database.py handles ALL file reads/writes
import api
import database

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
    # update.effective_user gives us the User object of whoever sent the message.
    # .first_name gets just their first name (e.g., "Lucas").
    user_first_name = update.effective_user.first_name

    # We'll use a multi-line string (triple quotes) for the message.
    # The \n creates a new line in the Telegram message.
    welcome_message = (
        f"🐀 Olá, {user_first_name}! Bem-vindo ao *RatFamilyBot*!\n\n"
        "Eu ajudo a galera a racharem o custo de jogos da Steam. "
        "Nada de planilha, tudo aqui no chat!\n\n"
        "📋 *O que eu faço:*\n"
        "  • Busco o preço atual e o menor preço histórico de jogos\n"
        "  • Registro quem quer participar do racha\n"
        "  • Calculo o valor por pessoa automaticamente\n\n"
        "⚙️ *Comandos disponíveis:*\n"
        "  /add `[URL da Steam]` — Adicionar um jogo\n"
        "  /want `[AppID ou Nome]` — Quero participar do racha!\n"
        "  /list — Ver todos os jogos e preços\n"
        "  /help — Mostra esta mensagem novamente\n\n"
        "Para começar, tente: `/add https://store.steampowered.com/app/1091500`"
    )

    # update.message.reply_text() sends a message back to the same chat.
    # parse_mode="Markdown" lets us use *bold* and `code` formatting in the text.
    await update.message.reply_text(welcome_message, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the /help command.
    Shows the user a clean list of all available commands and how to use them.
    """
    help_message = (
        "🎁 *RatFamilyBot — Comandos disponíveis*\n\n"
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
        "💡 *Dica:* Use `/add` com a URL completa da Steam para garantir que o jogo seja encontrado!"
    )

    await update.message.reply_text(help_message, parse_mode="Markdown")


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
        await update.message.reply_text(
            "⚠️ Você esqueceu a URL! Use assim:\n"
            "`/add https://store.steampowered.com/app/1091500/`",
            parse_mode="Markdown"
        )
        return

    raw_input = context.args[0]

    # --- STEP 2: Extract the AppID from the URL ---
    app_id = api.extract_app_id_from_url(raw_input)

    if not app_id:
        await update.message.reply_text(
            "❌ Link inválido! Precisa ser uma URL da Steam Store. Exemplo:\n"
            "`/add https://store.steampowered.com/app/1091500/`",
            parse_mode="Markdown"
        )
        return

    # --- STEP 3: Loading message (API calls take time) ---
    loading_message = await update.message.reply_text(
        f"🔍 Buscando informações para o AppID `{app_id}`...\n"
        "_(Isso pode levar alguns segundos)_",
        parse_mode="Markdown"
    )

    # --- STEP 4: Delegate to shared helper ---
    # _add_game_to_db() handles: Steam API → ITAD API → database.add_game()
    # This is the SINGLE source of truth for the "fetch + save" flow.
    # Both /add and /want use the same helper, avoiding duplicate logic.
    add_result = await _add_game_to_db(app_id)

    # --- STEP 5: Handle Steam API failure ---
    if add_result["status"] == "steam_error":
        await loading_message.edit_text(
            f"❌ Não encontrei nenhum jogo com AppID `{app_id}` na Steam.\n"
            "Verifique se o link está correto.",
            parse_mode="Markdown"
        )
        return

    game_name = add_result["game_name"]

    # --- STEP 6: Handle duplicate ---
    if add_result["status"] == "duplicate":
        await loading_message.edit_text(
            f"⚠️ *{game_name}* já está na nossa lista!\n"
            f"Use `/list` para ver todos os jogos.",
            parse_mode="Markdown"
        )
        return

    # --- STEP 7: Build confirmation with full price details ---
    # Fetch the saved game to display all fields (including ITAD data)
    game_data = await database.get_game_by_id(app_id)

    current_price = game_data["current_price"]
    best_deal_price = game_data["best_deal_price"]
    best_deal_shop = game_data["best_deal_shop"]
    historical_low = game_data["historical_low"]

    # Steam official price
    if current_price > 0:
        steam_str = f"R$ {current_price:.2f}"
    elif current_price == 0.0:
        steam_str = "Grátis 🎉"
    else:
        steam_str = "Indisponível"

    # Best deal (ITAD — may be different store)
    if best_deal_price >= 0:
        deal_str = f"R$ {best_deal_price:.2f}"
        if best_deal_shop:
            deal_str += f" _via {best_deal_shop}_"
    else:
        deal_str = "Sem promoções no momento"

    # Historical low
    if historical_low >= 0:
        low_str = f"R$ {historical_low:.2f}"
    else:
        low_str = "Dados não disponíveis"

    await loading_message.edit_text(
        f"✅ *{game_name}* adicionado com sucesso!\n\n"
        f"🎮 *AppID:* `{app_id}`\n"
        f"🏪 *Preço Steam (BRL):* {steam_str}\n"
        f"🔥 *Melhor deal agora:* {deal_str}\n"
        f"📉 *Menor preço histórico:* {low_str}\n\n"
        f"Use `/want {app_id}` para entrar no racha!",
        parse_mode="Markdown"
    )


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

    Used by add_command and want_command (Steam URL path).

    Returns a dict with the result of the operation:
      {
        "status": "added" | "duplicate" | "steam_error" | "ok",
        "game_name": str | None,
        "current_price": float,
      }
    """
    steam_info = api.get_steam_game_info(app_id)
    if steam_info is None:
        return {"status": "steam_error", "game_name": None, "current_price": -1.0}

    game_name = steam_info["name"]
    current_price = steam_info["current_price"]

    itad_data = api.get_itad_prices(app_id)
    if itad_data is not None:
        best_deal_price = itad_data["best_deal_price"]
        best_deal_shop  = itad_data.get("best_deal_shop", "")
        historical_low  = itad_data["historical_low"]
    else:
        best_deal_price = -1.0
        best_deal_shop  = ""
        historical_low  = -1.0

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
        await update.message.reply_text(
            "⚠️ Você precisa informar o jogo! Você pode usar:\n\n"
            "🔗 *Link da Steam* (adiciona e entra no racha automaticamente):\n"
            "`/want https://store.steampowered.com/app/1091500/`\n\n"
            "🔢 *AppID* (se o jogo já foi adicionado com `/add`):\n"
            "`/want 1091500`\n\n"
            "_O AppID aparece quando você usa `/add` ou `/list`._",
            parse_mode="Markdown"
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
            # Game already in DB — no need to call any API.
            # Just inform the user and let the want logic below handle the rest.
            await update.message.reply_text(
                f"ℹ️ *{existing_game['name']}* já está na lista!\n"
                "Registrando seu interesse...",
                parse_mode="Markdown"
            )
        else:
            # Game not in DB yet — run the full add flow.
            loading_message = await update.message.reply_text(
                f"🔍 Buscando o jogo na Steam...\n"
                "_(Isso pode levar alguns segundos)_",
                parse_mode="Markdown"
            )

            add_result = await _add_game_to_db(app_id)

            if add_result["status"] == "steam_error":
                await loading_message.edit_text(
                    f"❌ Não encontrei nenhum jogo com AppID `{app_id}` na Steam.\n"
                    "Verifique se o link está correto.",
                    parse_mode="Markdown"
                )
                return

            await loading_message.edit_text(
                f"✅ *{add_result['game_name']}* adicionado à lista!\n"
                "Registrando seu interesse...",
                parse_mode="Markdown"
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
        await update.message.reply_text(
            "❌ Entrada inválida! Use um link da Steam ou um AppID numérico:\n\n"
            "🔗 `/want https://store.steampowered.com/app/1091500/`\n"
            "🔢 `/want 1091500`",
            parse_mode="Markdown"
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
        # Only reachable via PATH B (AppID typed manually, game not in DB)
        await update.message.reply_text(
            f"❌ O jogo com AppID `{app_id}` não está na nossa lista.\n\n"
            "Para adicioná-lo, você pode:\n"
            "• Usar `/add [URL da Steam]`\n"
            "• Ou enviar o link direto no `/want`:\n"
            "  `/want https://store.steampowered.com/app/1091500/`",
            parse_mode="Markdown"
        )
        return

    if result == "duplicate":
        game = await database.get_game_by_id(app_id)
        game_name = game["name"] if game else app_id
        await update.message.reply_text(
            f"⚠️ Você já está no racha de *{game_name}*!\n"
            "Aguarda seus parceiros entrarem. 😄",
            parse_mode="Markdown"
        )
        return

    # result == "added" — success! Build confirmation message
    game = await database.get_game_by_id(app_id)
    if not game:
        await update.message.reply_text(
            f"✅ Interesse registrado no jogo `{app_id}`!",
            parse_mode="Markdown"
        )
        return

    game_name = game["name"]
    interested_users = game["interested_users"]
    total = len(interested_users)

    # Format the names list: @handle for usernames, plain name as fallback
    names = []
    for u in interested_users:
        uname = u["username"]
        names.append(f"@{uname}" if " " not in uname else uname)
    names_str = ", ".join(names)

    # Price per person calculation
    current_price = game.get("current_price", -1.0)
    if current_price > 0 and total > 0:
        per_person_str = f"R$ {(current_price / total):.2f} por pessoa"
    else:
        per_person_str = "Indisponível"

    await update.message.reply_text(
        f"✅ *{username}* entrou no racha de *{game_name}*!\n\n"
        f"👥 *Interessados ({total}):* {names_str}\n"
        f"💸 *Preço por pessoa:* {per_person_str}\n\n"
        f"_Quanto mais gente entrar, mais barato fica!_ 😎",
        parse_mode="Markdown"
    )



# =============================================================================
# /list COMMAND — Step 4 Implementation
# Shows all tracked games with prices, deal status, and split cost info.
# =============================================================================

def _format_price(price: float, fallback: str = "N/D") -> str:
    """
    Formats a float price as 'R$ X.XX', or returns a fallback string.
    Sentinel value -1.0 means the data wasn't available → shows fallback.
    This helper is used by both /list and /game to keep formatting consistent.
    """
    if price >= 0:
        return f"R$ {price:.2f}"
    return fallback


def _get_status_emoji(current_price: float, best_deal: float, historical_low: float) -> str:
    """
    Determines the deal status emoji for a game based on its price data.

    Rules (in priority order):
      🔥 — Current best deal equals (or is within R$0.01 of) the all-time low.
            This is the best moment to buy — never been cheaper!
      ✅ — Best deal is at least 30% cheaper than Steam's current price.
            A solid discount worth considering.
      ❌ — Neither condition met. Better to wait for a sale.

    Edge case: if we have no price data at all (all -1.0), returns ❓.

    Args:
        current_price: Steam official price in BRL (from Steam API).
        best_deal:     Best current deal across all stores (from ITAD).
        historical_low: All-time lowest price ever (from ITAD).
    """
    # Can't assess without usable price data
    if current_price < 0 and best_deal < 0:
        return "❓"

    # Use best_deal if available, otherwise fall back to steam price
    reference_price = best_deal if best_deal >= 0 else current_price

    # 🔥 At (or tied with) all-time low
    if historical_low >= 0 and reference_price <= historical_low + 0.01:
        return "🔥"

    # ✅ At least 30% off Steam's listed price
    if current_price > 0 and best_deal >= 0:
        discount_pct = (current_price - best_deal) / current_price * 100
        if discount_pct >= 30:
            return "✅"

    # ❌ No meaningful deal right now
    return "❌"


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the /list command. Shows all tracked games with:
      - Status emoji (🔥 / ✅ / ❌)
      - Steam price, best current deal, historical low
      - Number of interested people and who they are
      - Price per person (Steam price ÷ interested count)

    Edge cases handled:
      - Empty database → friendly onboarding message
      - Games with no price data → shows N/D gracefully
      - Free games → shows "Grátis 🎉" instead of R$ 0.00
      - No interested users → skips per-person calculation
      - Long lists → splits into multiple messages (Telegram's 4096-char limit)
    """
    games = await database.get_all_games()

    # --- Empty state: the list has no games yet ---
    if not games:
        await update.message.reply_text(
            "📭 *A lista está vazia!*\n\n"
            "Nenhum jogo foi adicionado ainda.\n"
            "Use `/add [URL da Steam]` para adicionar o primeiro! 🎮",
            parse_mode="Markdown"
        )
        return

    # --- Build the message, one block per game ---
    # We build a list of strings (one per game) and join them at the end.
    # This makes it easy to split into multiple messages if needed.
    game_blocks = []

    for app_id, game in games.items():
        name          = game.get("name", "Jogo Desconhecido")
        current_price = game.get("current_price", -1.0)
        best_deal     = game.get("best_deal_price", -1.0)
        deal_shop     = game.get("best_deal_shop", "")
        hist_low      = game.get("historical_low", -1.0)
        interested    = game.get("interested_users", [])
        total         = len(interested)

        # --- Status emoji ---
        status = _get_status_emoji(current_price, best_deal, hist_low)

        # --- Price strings ---
        if current_price == 0.0:
            steam_str = "Grátis 🎉"
        else:
            steam_str = _format_price(current_price)

        # Melhor deal: include the shop name if available
        deal_str = _format_price(best_deal)
        if deal_shop and best_deal >= 0:
            deal_str += f" ({deal_shop})"

        low_str  = _format_price(hist_low)

        # --- Interested people ---
        if total == 0:
            people_str    = "Ninguém ainda"
            per_person_str = "—"
        else:
            names = []
            for u in interested:
                uname = u.get("username", "?")
                names.append(f"@{uname}" if " " not in uname else uname)
            people_str = f"({total}) {', '.join(names)}"

            # Per-person uses the best available price
            split_price = best_deal if best_deal >= 0 else current_price
            if split_price > 0:
                per_person_str = f"R$ {(split_price / total):.2f}"
            else:
                per_person_str = "—"

        block = (
            f"{status} *{name}* — `{app_id}`\n"
            f"  🏪 Steam: {steam_str}  |  🔥 Melhor Deal: {deal_str}  |  📉 Mín.: {low_str}\n"
            f"  👥 {people_str}\n"
            f"  💸 Por pessoa: {per_person_str}"
        )
        game_blocks.append(block)

    # --- Assemble and send, respecting Telegram's 4096-char message limit ---
    # We group blocks into chunks that fit within the limit.
    header = f"🎮 *Lista de jogos ({len(games)} jogo{'s' if len(games) != 1 else ''})*\n\n"
    TELEGRAM_LIMIT = 4096
    SEPARATOR = "\n\n"

    current_chunk = header
    for block in game_blocks:
        candidate = current_chunk + block + SEPARATOR
        if len(candidate) > TELEGRAM_LIMIT:
            # Current chunk is full — send it and start a new one
            await update.message.reply_text(current_chunk.strip(), parse_mode="Markdown")
            current_chunk = block + SEPARATOR
        else:
            current_chunk = candidate

    # Send whatever's left in the last chunk
    if current_chunk.strip():
        await update.message.reply_text(current_chunk.strip(), parse_mode="Markdown")



# =============================================================================
# MODULE CONSTANTS — Status Labels
# Human-readable descriptions for each deal status emoji.
# Used by game_command() and potentially other formatters.
# =============================================================================

STATUS_LABELS: dict[str, str] = {
    "🔥": "🔥 *MENOR PREÇO HISTÓRICO!*",
    "✅": "✅ *Bom preço* (30%+ de desconto)",
    "❌": "❌ *Aguardar* — sem promoção relevante",
    "❓": "❓ *Sem dados de preço suficientes*",
}


# =============================================================================
# /game COMMAND — Step 5 Implementation
# Shows detailed info for a SINGLE game, including full interested list.
# =============================================================================

async def game_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the /game [AppID] command. Shows full detail for a specific game.

    Unlike /list (which shows a compact summary of ALL games), /game gives you
    the full breakdown for ONE game: all price tiers, status, every interested
    user listed with numbers, and the per-person split cost.

    Edge cases handled:
      - No argument → usage instructions
      - Steam URL given instead of AppID → helpful redirect message
      - Non-numeric text → error with example
      - AppID not in database → suggests using /add
      - Game with no interested users → shows "ninguém ainda"
      - Game with no price data → shows N/D gracefully
    """
    # --- STEP 1: Validate that an AppID was provided ---
    if not context.args:
        await update.message.reply_text(
            "⚠️ Informe o AppID do jogo! Use assim:\n"
            "`/game 1091500`\n\n"
            "_O AppID aparece quando você usa `/add` ou `/list`._",
            parse_mode="Markdown"
        )
        return

    raw_input = context.args[0].strip()

    # --- STEP 2: Detect if user pasted a Steam URL instead of AppID ---
    # This is a common mistake. Instead of just saying "invalid", we extract
    # the AppID from the URL and tell them the correct command.
    # Good UX = anticipate the user's mistake and guide them gently.
    extracted = api.extract_app_id_from_url(raw_input)
    if extracted:
        await update.message.reply_text(
            f"💡 Parece que você colou um link da Steam!\n"
            f"O comando `/game` usa apenas o AppID. Tente:\n\n"
            f"`/game {extracted}`",
            parse_mode="Markdown"
        )
        return

    # --- STEP 3: Validate that input is numeric ---
    if not raw_input.isdigit():
        await update.message.reply_text(
            "❌ AppID inválido! O AppID é numérico. Exemplo:\n"
            "`/game 1091500`",
            parse_mode="Markdown"
        )
        return

    app_id = raw_input

    # --- STEP 4: Fetch game from database ---
    game = await database.get_game_by_id(app_id)

    if not game:
        await update.message.reply_text(
            f"❌ Nenhum jogo com AppID `{app_id}` foi encontrado na lista.\n\n"
            "Para adicioná-lo, use:\n"
            "`/add https://store.steampowered.com/app/"
            f"{app_id}/`",
            parse_mode="Markdown"
        )
        return

    # --- STEP 5: Extract all data from the game record ---
    name          = game.get("name", "Jogo Desconhecido")
    current_price = game.get("current_price", -1.0)
    best_deal     = game.get("best_deal_price", -1.0)
    deal_shop     = game.get("best_deal_shop", "")
    hist_low      = game.get("historical_low", -1.0)
    interested    = game.get("interested_users", [])
    total         = len(interested)

    # --- Status emoji (reuses the same helper from /list) ---
    status = _get_status_emoji(current_price, best_deal, hist_low)

    # --- STEP 6: Format price strings ---
    # Using the shared _format_price helper for consistency with /list
    if current_price == 0.0:
        steam_str = "Grátis 🎉"
    else:
        steam_str = _format_price(current_price)

    # Melhor deal: append "(via Shop)" when available
    deal_str = _format_price(best_deal)
    if deal_shop and best_deal >= 0:
        deal_str += f" _(via {deal_shop})_"

    low_str  = _format_price(hist_low)

    # --- STEP 7: Format interested users list ---
    # /game shows a NUMBERED list (unlike /list which shows inline names).
    # This makes it easy to see exactly who's in and count visually.
    if total == 0:
        people_block = "  _Ninguém ainda — use_ `/want " + app_id + "` _para entrar!_"
        per_person_str = "—"
    else:
        # Build numbered list: "  1. @lucas\n  2. @joao\n  3. Maria"
        lines = []
        for i, u in enumerate(interested, start=1):
            uname = u.get("username", "?")
            display = f"@{uname}" if " " not in uname else uname
            lines.append(f"  {i}. {display}")
        people_block = "\n".join(lines)

        # Price per person — uses the best available price for the split
        split_price = best_deal if best_deal >= 0 else current_price
        if split_price > 0:
            per_person_str = f"R$ {(split_price / total):.2f}"
        else:
            per_person_str = "—"

    # --- STEP 8: Build and send the detail message ---
    # Status line — gives a human-readable explanation of the emoji
    status_line = STATUS_LABELS.get(status, status)

    message = (
        f"🎮 *{name}*\n"
        f"📋 AppID: `{app_id}`\n\n"
        f"*💰 Preços (BRL):*\n"
        f"  🏪 Steam: {steam_str}\n"
        f"  🔥 Melhor deal: {deal_str}\n"
        f"  📉 Mínimo histórico: {low_str}\n\n"
        f"*📊 Status:* {status_line}\n\n"
        f"*👥 Interessados ({total}):*\n"
        f"{people_block}\n\n"
        f"*💸 Preço por pessoa:* {per_person_str}"
    )

    await update.message.reply_text(message, parse_mode="Markdown")




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
    print("🐀 Starting RatFamilyBot...")
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
    print("✅ Bot is running! Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


# =============================================================================
# ENTRY POINT GUARD
# This "if __name__ == '__main__':" block means: only run main() if this file
# is executed directly (python bot.py), NOT when it's imported by another file.
# It's a Python best practice you'll see in almost every project.
# =============================================================================
if __name__ == "__main__":
    main()
