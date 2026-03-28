# =============================================================================
# api.py - All External API Communication
# =============================================================================
# PRICE STRATEGY (3 sources):
#   1. Steam API  → Game NAME + current official price in BRL (cc=br)
#   2. ITAD Prices → Best current promotional deal across ALL stores (BRL)
#   3. ITAD History → All-time historical low price (BRL)
#
# WHY THREE SOURCES?
#   Steam gives us the "face" price. ITAD may show a cheaper deal right now
#   (e.g., Nuuvem, Fanatical, etc.) or reveal how low it has ever gone.
#   This gives the family group the full picture when deciding to split costs.
#
# AUTHENTICATION:
#   - Steam: no key needed
#   - ITAD: API key from .env → https://isthereanydeal.com/apps/my/
# =============================================================================

import os
import re
import requests
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10  # seconds — never make requests without a timeout!

ITAD_API_KEY = os.getenv("ITAD_API_KEY")
ITAD_BASE_URL = "https://api.isthereanydeal.com"


# =============================================================================
# URL PARSER
# =============================================================================

def extract_app_id_from_url(url: str) -> str | None:
    """
    Extracts the Steam AppID from a Steam store URL using regex.

    Handles:
      ✅ https://store.steampowered.com/app/1091500/Cyberpunk_2077/
      ✅ https://store.steampowered.com/app/1091500
      ✅ store.steampowered.com/app/1091500  (no protocol)
      ❌ https://www.google.com              (returns None)

    Returns:
        str | None: AppID (e.g. "1091500"), or None if URL is invalid.
    """
    match = re.search(r"/app/(\d+)", url)
    if match:
        return match.group(1)
    return None


# =============================================================================
# SOURCE 1: Steam API — Game Name + Official BRL Price
# =============================================================================

def get_steam_game_info(app_id: str) -> dict | None:
    """
    Fetches the game name and current BRL price from the Steam Storefront API.

    The Steam API returns price in CENTS (integer), so we divide by 100.
    Example: "final": 19990 → R$ 199,90

    Edge cases:
      ✅ Paid game → returns name + price
      ✅ Free-to-play → price_overview is absent → price = 0.0
      ✅ AppID not found → returns None
      ✅ Network error/timeout → returns None

    Returns:
        dict | None: {"name": str, "current_price": float (BRL)} or None.
    """
    url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=br"
    logger.info(f"[Steam API] Fetching name+price for AppID: {app_id}")

    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        app_data = data.get(app_id, {})
        if not app_data.get("success"):
            logger.warning(f"[Steam API] AppID {app_id} not found or invalid.")
            return None

        game_data = app_data.get("data", {})
        name = game_data.get("name", "Unknown Game")

        # price_overview is absent for free games
        price_overview = game_data.get("price_overview")
        if price_overview:
            # "final" = price after discount, in CENTS
            current_price = price_overview.get("final", 0) / 100
        else:
            current_price = 0.0  # Free-to-play

        logger.info(f"[Steam API] '{name}' → R$ {current_price:.2f}")
        return {"name": name, "current_price": current_price}

    except requests.exceptions.Timeout:
        logger.error(f"[Steam API] Timeout for AppID: {app_id}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"[Steam API] Network error: {e}")
        return None
    except (ValueError, KeyError) as e:
        logger.error(f"[Steam API] Parse error: {e}")
        return None


# =============================================================================
# ITAD INTERNAL HELPER — Steam AppID → ITAD UUID
# =============================================================================

def _get_itad_uuid(app_id: str) -> str | None:
    """
    Converts a Steam AppID into ITAD's internal UUID.

    ITAD uses UUIDs (e.g. "018d937f-012f-73b8-ab2c-898516969e6a") to identify
    games across stores. We must resolve the Steam AppID before querying prices.

    Request body format: ["app/1091500"]
    Response format:     {"app/1091500": "018d937f-...", ...}
    A null value means ITAD doesn't track this game.

    Returns:
        str | None: ITAD UUID, or None if not found / API key missing.
    """
    if not ITAD_API_KEY or ITAD_API_KEY == "sua_chave_aqui":
        logger.error("[ITAD] API key not configured! Set ITAD_API_KEY in .env")
        return None

    shop_game_id = f"app/{app_id}"
    logger.info(f"[ITAD Lookup] Resolving Steam AppID {app_id} → UUID")

    try:
        response = requests.post(
            f"{ITAD_BASE_URL}/lookup/gid/id/v1",
            json=[shop_game_id],
            params={"key": ITAD_API_KEY},
            timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()

        data = response.json()
        itad_uuid = data.get(shop_game_id)

        if not itad_uuid:
            logger.warning(f"[ITAD Lookup] No UUID for {shop_game_id}")
            return None

        logger.info(f"[ITAD Lookup] UUID → {itad_uuid}")
        return itad_uuid

    except requests.exceptions.Timeout:
        logger.error(f"[ITAD Lookup] Timeout for AppID: {app_id}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"[ITAD Lookup] Network error: {e}")
        return None
    except (ValueError, KeyError) as e:
        logger.error(f"[ITAD Lookup] Parse error: {e}")
        return None


# =============================================================================
# SOURCES 2 & 3: ITAD — Best Current Deal + Historical Low (both in BRL)
# =============================================================================

def get_itad_prices(app_id: str) -> dict | None:
    """
    Fetches the best current promotional deal AND historical low from ITAD.
    Both prices are in BRL (country=BR).

    IMPORTANT DISTINCTION vs Steam API:
      - Steam price (get_steam_game_info) = official Steam BR price.
        Always available, reflects Steam's current listed price.
      - ITAD best deal (this function) = cheapest price RIGHT NOW across
        all tracked stores (Nuuvem, Fanatical, GreenManGaming, etc.).
        May be lower than Steam if a key store is running a sale.
      - ITAD historical low = lowest price ever recorded, any store.

    The deals from ITAD are NOT filtered by shop, so we get the best price
    regardless of where the deal is. This is the most useful for price hunting.

    Internally runs 3 API calls:
      1. _get_itad_uuid() — Steam AppID → ITAD UUID
      2. POST /games/prices/v3?country=BR — current best deal
      3. POST /games/historylow/v1?country=BR — all-time low

    Sentinel value: -1.0 = "data not available" (stored in JSON as -1.0).

    Returns:
        dict | None: {
            "best_deal_price": float,   # Best current price in BRL (-1.0 = N/A)
            "best_deal_shop": str,      # Store name (e.g. "Nuuvem", "Steam")
            "best_deal_cut": int,       # Discount % (0 = no discount)
            "historical_low": float,    # All-time low in BRL (-1.0 = N/A)
            "historical_low_shop": str, # Store where low was seen
            "historical_low_cut": int,  # Discount % at historical low
        }
        Returns None only if the ITAD UUID lookup fails (game unknown to ITAD).
    """
    itad_uuid = _get_itad_uuid(app_id)
    if itad_uuid is None:
        return None

    payload = [itad_uuid]
    country = "BR"

    result = {
        "best_deal_price": -1.0,
        "best_deal_shop": "",
        "best_deal_cut": 0,
        "historical_low": -1.0,
        "historical_low_shop": "",
        "historical_low_cut": 0,
    }

    # --- SOURCE 2: Best current deal (no shop filter = best across all stores) ---
    try:
        logger.info(f"[ITAD Prices] Fetching best current deal for {itad_uuid}")
        price_resp = requests.post(
            f"{ITAD_BASE_URL}/games/prices/v3",
            json=payload,
            params={"key": ITAD_API_KEY, "country": country},
            timeout=REQUEST_TIMEOUT
        )
        price_resp.raise_for_status()
        price_data = price_resp.json()

        # Response: [{id, historyLow, deals: [{shop, price, regular, cut, ...}]}]
        # deals[] is already sorted by price ascending — deals[0] = cheapest
        if price_data:
            deals = price_data[0].get("deals", [])
            if deals:
                best = deals[0]  # First deal = cheapest right now
                amount = best.get("price", {}).get("amount")
                if amount is not None:
                    result["best_deal_price"] = float(amount)
                    result["best_deal_shop"] = best.get("shop", {}).get("name", "?")
                    result["best_deal_cut"] = best.get("cut", 0)
                    logger.info(
                        f"[ITAD Prices] Best deal: R$ {result['best_deal_price']:.2f} "
                        f"({result['best_deal_cut']}% off at {result['best_deal_shop']})"
                    )
            else:
                logger.warning("[ITAD Prices] No current deals found")

    except requests.exceptions.Timeout:
        logger.error(f"[ITAD Prices] Timeout for UUID: {itad_uuid}")
    except requests.exceptions.RequestException as e:
        logger.error(f"[ITAD Prices] Network error: {e}")
    except (ValueError, KeyError, IndexError) as e:
        logger.error(f"[ITAD Prices] Parse error: {e}")

    # --- SOURCE 3: Historical low (all-time, any store) ---
    try:
        logger.info(f"[ITAD History] Fetching historical low for {itad_uuid}")
        hist_resp = requests.post(
            f"{ITAD_BASE_URL}/games/historylow/v1",
            json=payload,
            params={"key": ITAD_API_KEY, "country": country},
            timeout=REQUEST_TIMEOUT
        )
        hist_resp.raise_for_status()
        hist_data = hist_resp.json()

        # Response: [{id, low: {shop, price, regular, cut, timestamp}}]
        if hist_data:
            low_entry = hist_data[0].get("low")
            if low_entry:
                amount = low_entry.get("price", {}).get("amount")
                if amount is not None:
                    result["historical_low"] = float(amount)
                    result["historical_low_shop"] = low_entry.get("shop", {}).get("name", "?")
                    result["historical_low_cut"] = low_entry.get("cut", 0)
                    logger.info(
                        f"[ITAD History] Low: R$ {result['historical_low']:.2f} "
                        f"({result['historical_low_cut']}% off at {result['historical_low_shop']})"
                    )

    except requests.exceptions.Timeout:
        logger.error(f"[ITAD History] Timeout for UUID: {itad_uuid}")
    except requests.exceptions.RequestException as e:
        logger.error(f"[ITAD History] Network error: {e}")
    except (ValueError, KeyError, IndexError) as e:
        logger.error(f"[ITAD History] Parse error: {e}")

    return result
