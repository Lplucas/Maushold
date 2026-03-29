# =============================================================================
# database.py — Camada de persistência (I/O assíncrono via aiofiles)
# =============================================================================
# Responsável por TODA leitura e escrita no banco de dados (database.json).
# Usa aiofiles para I/O não-bloqueante, garantindo que o event loop do bot
# não seja paralisado durante operações de disco.
#
# PADRÃO DE I/O:
#   - Leitura: aiofiles.open() → await f.read() → json.loads(string)
#   - Escrita: json.dumps(dict) → aiofiles.open() → await f.write(string)
#   A separação entre serialização (json.loads/dumps, em memória) e I/O
#   (aiofiles.open/read/write) é intencional — minimiza a janela de arquivo
#   aberto e permite I/O verdadeiramente assíncrono.
#
# RESILIÊNCIA:
#   - Arquivo inexistente → retorna banco vazio (FileNotFoundError)
#   - JSON corrompido → retorna banco vazio (JSONDecodeError) + log de erro
#   Nenhum caso causa crash do bot.
#
# WHY A SEPARATE FILE?
#   Keeping database logic here (instead of in bot.py) is called "separation of
#   concerns". If something breaks with saving/loading data, we know exactly
#   where to look.
# =============================================================================

import json      # json.loads() para parsing, json.dumps() para serialização
import asyncio   # Used for the Lock to prevent race conditions
import logging   # Structured logging — observabilidade consistente
import aiofiles  # I/O assíncrono de arquivos — substitui open() nativo

logger = logging.getLogger(__name__)


# --- CONSTANTS ---
# A constant is a variable we never change. Using a constant for the filename
# means if we ever rename the file, we only have to change it in ONE place.
DATABASE_FILE = "database.json"

# --- THE LOCK (O CADEADO) ---
# This is our single "padlock" for the entire database file.
# We create one global lock here that all functions will share.
# When a function is reading or writing to the file, it will "acquire" (lock) it.
# If another function tries to do the same, it must wait until the lock is "released" (unlocked).
db_lock = asyncio.Lock()


async def load_database() -> dict:
    """
    Carrega o banco de dados a partir do arquivo JSON.

    Usa aiofiles para leitura não-bloqueante. O conteúdo é lido como string
    (await f.read()) e depois convertido para dict via json.loads() — operação
    em memória, síncrona e rápida.

    Casos de erro tratados:
      - FileNotFoundError → primeiro uso, retorna {"games": {}}
      - json.JSONDecodeError → arquivo corrompido, retorna {"games": {}} + log

    Returns:
        dict: O banco de dados completo como dicionário Python.
    """
    # We lock the padlock BEFORE touching the file.
    # The 'async with' automatically locks it here, and unlocks it when the block ends.
    async with db_lock:
        try:
            # aiofiles.open() é a versão assíncrona do open() nativo.
            # A diferença: o I/O acontece sem bloquear o event loop do bot.
            async with aiofiles.open(DATABASE_FILE, "r", encoding="utf-8") as f:
                content = await f.read()         # Lê todo o conteúdo como string
            data = json.loads(content)           # Converte string → dict (em memória, rápido)
            return data
        except FileNotFoundError:
            # First run! Return a default empty structure.
            logger.info("Arquivo '%s' não encontrado. Iniciando banco vazio.", DATABASE_FILE)
            return {"games": {}}
        except json.JSONDecodeError:
            # Arquivo corrompido — resiliência: retorna vazio em vez de crashar.
            # O arquivo corrompido NÃO é deletado automaticamente — permite investigação.
            logger.error("Arquivo '%s' corrompido! Retornando banco vazio.", DATABASE_FILE)
            return {"games": {}}


async def save_database(data: dict) -> None:
    """
    Serializa o dicionário e salva no arquivo JSON.

    Estratégia de escrita segura:
      1. json.dumps() converte dict → string EM MEMÓRIA (rápido)
      2. aiofiles.open("w") abre o arquivo
      3. await f.write(content) escreve a string de uma vez

    Gerar a string ANTES de abrir o arquivo minimiza a janela de risco:
    quanto menos tempo o arquivo fica aberto para escrita, menor a chance
    de corrupção por interrupção (ex: processo encerrado abruptamente).

    Args:
        data (dict): O dicionário completo do banco de dados para salvar.
    """
    # We lock the padlock BEFORE writing.
    # Even if someone is reading, they must finish and unlock before we can write.
    async with db_lock:
        # Passo 1: Serializa para string em memória (operação síncrona, rápida)
        content = json.dumps(data, indent=4, ensure_ascii=False)
        # Passo 2: Abre o arquivo e escreve de uma vez (I/O assíncrono)
        async with aiofiles.open(DATABASE_FILE, "w", encoding="utf-8") as f:
            await f.write(content)
        logger.info("Banco de dados salvo com sucesso.")


async def add_game(
    app_id: str,
    name: str,
    current_price: float,
    best_deal_price: float,
    best_deal_shop: str,
    historical_low: float
) -> bool:
    """
    Adds a new game to the database.

    Args:
        app_id (str): The Steam AppID (e.g., "1091500" for Cyberpunk 2077).
        name (str): The game's official name.
        current_price (float): Current Steam price in BRL (from Steam API).
        best_deal_price (float): Best current deal across all stores in BRL
                                  (from ITAD). -1.0 = no deal / not available.
        best_deal_shop (str): Name of the store with the best deal (e.g. "Nuuvem").
                              Empty string if no deal is available.
        historical_low (float): All-time lowest price in BRL (from ITAD).
                                 -1.0 = data not available.

    Returns:
        bool: True if the game was added, False if it already existed.
    """
    data = await load_database()

    # Check if this game is already in our list to avoid duplicates.
    if app_id in data["games"]:
        logger.info("Jogo '%s' (AppID: %s) já existe no banco.", name, app_id)
        return False  # Signal to the bot that it was a duplicate

    # Add the new game entry. This is the structure for a single game.
    data["games"][app_id] = {
        "name": name,
        "app_id": app_id,
        "current_price": current_price,       # Steam official price in BRL
        "best_deal_price": best_deal_price,   # Best promo deal (ITAD) in BRL
        "best_deal_shop": best_deal_shop,     # Store name (e.g. "Nuuvem")
        "historical_low": historical_low,     # All-time low (ITAD) in BRL
        "interested_users": []                # List of user IDs who want to split
        # Example after a few /want commands:
        # "interested_users": [
        #   {"user_id": 123456, "username": "lucas"},
        #   {"user_id": 789012, "username": "joao"}
        # ]
    }

    await save_database(data)
    logger.info("Jogo '%s' adicionado com AppID %s.", name, app_id)
    return True  # Signal to the bot that it was added successfully


async def get_all_games() -> dict:
    """
    Returns the entire 'games' dictionary from the database.

    Returns:
        dict: All games, keyed by their AppID string.
    """
    data = await load_database()
    return data.get("games", {})  # .get() is safe: returns {} if key missing


async def get_game_by_id(app_id: str) -> dict | None:
    """
    Finds and returns a single game by its AppID.

    Args:
        app_id (str): The Steam AppID to look up.

    Returns:
        dict | None: The game data dict, or None if not found.
    """
    games = await get_all_games()
    return games.get(app_id)  # Returns None automatically if key doesn't exist


async def add_interested_user(app_id: str, user_id: int, username: str) -> str:
    """
    Adds a user to a game's 'interested_users' list.

    Args:
        app_id (str): The Steam AppID of the game.
        user_id (int): Telegram's unique numeric ID for the user.
        username (str): The user's Telegram @username (can be None).

    Returns:
        str: A status string — "added", "duplicate", or "not_found".
    """
    data = await load_database()

    # First, make sure the game exists.
    if app_id not in data["games"]:
        return "not_found"

    interested_list = data["games"][app_id]["interested_users"]

    # Check if this user is already in the list. We compare by user_id because
    # usernames can change, but Telegram user IDs are permanent.
    for user in interested_list:
        if user["user_id"] == user_id:
            return "duplicate"

    # User is not in the list, so add them!
    interested_list.append({
        "user_id": user_id,
        "username": username or "unknown"  # Handle users with no @username
    })

    await save_database(data)
    return "added"
