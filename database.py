# =============================================================================
# database.py - The "brain storage" of our bot
# =============================================================================
# This file is responsible for ALL reading and writing to our database.
# Our "database" is just a JSON file (database.json). Think of it like a
# notebook that the bot writes to and reads from whenever it needs to remember
# something.
#
# WHY A SEPARATE FILE?
# Keeping database logic here (instead of in bot.py) is called "separation of
# concerns". It keeps our code clean and easy to fix: if something breaks with
# saving/loading data, we know exactly where to look.
# =============================================================================

import json      # Python's built-in library for reading/writing JSON files
import asyncio   # Used for the Lock to prevent race conditions
import logging   # Structured logging — substitui print() para observabilidade consistente

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
    Reads the database.json file and returns its contents as a Python dict.

    If the file doesn't exist yet (first time running the bot), it creates
    a fresh, empty database structure and returns that instead.

    Returns:
        dict: The entire database as a Python dictionary.
    """
    # We lock the padlock BEFORE touching the file. 
    # The 'async with' automatically locks it here, and unlocks it when the block ends.
    async with db_lock:
        try:
            # 'r' means "read-only mode". 'encoding="utf-8"' handles special characters
            # like accents (é, ã) correctly.
            with open(DATABASE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)  # json.load() converts JSON text → Python dict
            return data
        except FileNotFoundError:
            # First run! Return a default empty structure.
            logger.info("Arquivo '%s' não encontrado. Iniciando banco vazio.", DATABASE_FILE)
            return {"games": {}}
        except json.JSONDecodeError:
            # Arquivo corrompido — resiliência: retorna vazio em vez de crashar.
            # Isso impede que um arquivo danificado torne o bot inutilizável.
            logger.error("Arquivo '%s' corrompido! Retornando banco vazio.", DATABASE_FILE)
            return {"games": {}}


async def save_database(data: dict) -> None:
    """
    Takes a Python dictionary and writes it to database.json, overwriting it.

    Args:
        data (dict): The full database dictionary to save.
    """
    # We lock the padlock BEFORE writing.
    # Even if someone is reading, they must finish and unlock before we can write.
    async with db_lock:
        # 'w' means "write mode" — it creates the file if it doesn't exist,
        # or overwrites it completely if it does.
        with open(DATABASE_FILE, "w", encoding="utf-8") as f:
            # json.dump() converts Python dict → JSON text and writes to the file.
            # indent=4 makes the JSON file human-readable (nicely indented).
            # ensure_ascii=False allows characters like ã, é to be saved correctly.
            json.dump(data, f, indent=4, ensure_ascii=False)
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
