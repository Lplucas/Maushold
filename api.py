# =============================================================================
# api.py — Comunicação com APIs externas (I/O assíncrono via aiohttp)
# =============================================================================
# ESTRATÉGIA DE PREÇOS (3 fontes):
#   1. Steam API  → Nome do jogo + preço oficial em BRL (cc=br)
#   2. ITAD Prices → Melhor deal atual em TODAS as lojas (BRL)
#   3. ITAD History → Menor preço histórico de todos os tempos (BRL)
#
# POR QUE TRÊS FONTES?
#   A Steam dá o preço "de vitrine". A ITAD pode mostrar um deal mais barato
#   em outra loja (Nuuvem, Fanatical, etc.) ou revelar o menor preço histórico.
#   Isso dá ao grupo familiar a visão completa para decidir se vale rachar.
#
# AUTENTICAÇÃO:
#   - Steam: sem chave necessária
#   - ITAD: API key via .env → https://isthereanydeal.com/apps/my/
#
# I/O ASSÍNCRONO:
#   Todas as chamadas HTTP usam aiohttp (não-bloqueante). Cada função cria uma
#   ClientSession e a fecha ao terminar. Em sprints futuras, a sessão será
#   compartilhada para reutilizar conexões TCP.
#
# EXCEÇÕES (vs requests):
#   - Timeout:  asyncio.TimeoutError    (antes: requests.exceptions.Timeout)
#   - Rede:     aiohttp.ClientError     (antes: requests.exceptions.RequestException)
#   - Parsing:  ValueError, KeyError    (sem mudança — erros de dados, não de rede)
# =============================================================================

import os
import re
import asyncio
import logging

import aiohttp
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10  # seconds — never make requests without a timeout!

ITAD_API_KEY = os.getenv("ITAD_API_KEY")
ITAD_BASE_URL = "https://api.isthereanydeal.com"

# Padrão compilado para extrair AppID de URLs Steam.
# re.compile() executa a compilação da regex uma única vez na inicialização
# do módulo, em vez de recompilar a cada chamada de extract_app_id_from_url().
# Ganho: ~50% mais rápido em chamadas repetidas (micro-otimização, mas gratuita).
STEAM_APP_RE = re.compile(r"/app/(\d+)")


# =============================================================================
# URL PARSER (sync — não faz I/O, apenas processa string)
# =============================================================================

def extract_app_id_from_url(url: str) -> str | None:
    """
    Extracts the Steam AppID from a Steam store URL using regex.

    This function is intentionally synchronous — it does not perform I/O,
    only processes a string in memory. Sync functions can coexist with
    async functions in the same module without any issue.

    Handles:
      ✅ https://store.steampowered.com/app/1091500/Cyberpunk_2077/
      ✅ https://store.steampowered.com/app/1091500
      ✅ store.steampowered.com/app/1091500  (no protocol)
      ❌ https://www.google.com              (returns None)

    Args:
        url (str): A URL string to extract the AppID from.

    Returns:
        str | None: AppID (e.g. "1091500"), or None if URL is invalid.
    """
    match = STEAM_APP_RE.search(url)
    if match:
        return match.group(1)
    return None


# =============================================================================
# SOURCE 1: Steam API — Game Name + Official BRL Price
# =============================================================================

async def get_steam_game_info(app_id: str) -> dict | None:
    """
    Fetches the game name and current BRL price from the Steam Storefront API.

    Usa aiohttp para chamada HTTP não-bloqueante. A resposta é lida com
    await response.json() — necessário porque o corpo chega em chunks pela rede.

    The Steam API returns price in CENTS (integer), so we divide by 100.
    Example: "final": 19990 → R$ 199,90

    Edge cases:
      ✅ Paid game → returns name + price
      ✅ Free-to-play → price_overview is absent → price = 0.0
      ✅ AppID not found → returns None
      ✅ Network error/timeout → returns None

    Args:
        app_id (str): Steam AppID to look up.

    Returns:
        dict | None: {"name": str, "current_price": float (BRL)} or None.

    Raises:
        Nenhuma — erros de rede e parsing são capturados internamente
        e resultam em retorno None com log de erro.
    """
    url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=br"
    logger.info("[Steam API] Fetching name+price for AppID: %s", app_id)

    try:
        # aiohttp usa dois 'async with' aninhados:
        #   1. ClientSession = "navegador" que gerencia conexões e config
        #   2. session.get()  = uma requisição específica dentro da sessão
        # A sessão é criada e destruída aqui; em sprints futuras será compartilhada.
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                response.raise_for_status()
                data = await response.json()

        app_data = data.get(app_id, {})
        if not app_data.get("success"):
            logger.warning("[Steam API] AppID %s not found or invalid.", app_id)
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

        logger.info("[Steam API] '%s' → R$ %.2f", name, current_price)
        return {"name": name, "current_price": current_price}

    # asyncio.TimeoutError substitui requests.exceptions.Timeout.
    # aiohttp usa as exceções do próprio asyncio para timeout.
    except asyncio.TimeoutError:
        logger.error("[Steam API] Timeout for AppID: %s", app_id)
        return None
    # aiohttp.ClientError substitui requests.exceptions.RequestException.
    # Cobre: ConnectionError, HttpProcessingError, ServerDisconnectedError, etc.
    except aiohttp.ClientError as e:
        logger.error("[Steam API] Network error: %s", e)
        return None
    except (ValueError, KeyError) as e:
        logger.error("[Steam API] Parse error: %s", e)
        return None


# =============================================================================
# ITAD INTERNAL HELPER — Steam AppID → ITAD UUID
# =============================================================================

async def _get_itad_uuid(app_id: str) -> str | None:
    """
    Converts a Steam AppID into ITAD's internal UUID.

    Função interna (prefixo _) — deve ser chamada apenas dentro deste módulo.
    Usa aiohttp para POST assíncrono. Requer await ao chamar.

    ITAD uses UUIDs (e.g. "018d937f-012f-73b8-ab2c-898516969e6a") to identify
    games across stores. We must resolve the Steam AppID before querying prices.

    Request body format: ["app/1091500"]
    Response format:     {"app/1091500": "018d937f-...", ...}
    A null value means ITAD doesn't track this game.

    Args:
        app_id (str): Steam AppID to resolve.

    Returns:
        str | None: ITAD UUID, or None if not found / API key missing.
    """
    if not ITAD_API_KEY or ITAD_API_KEY == "sua_chave_aqui":
        logger.error("[ITAD] API key not configured! Set ITAD_API_KEY in .env")
        return None

    shop_game_id = f"app/{app_id}"
    logger.info("[ITAD Lookup] Resolving Steam AppID %s → UUID", app_id)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{ITAD_BASE_URL}/lookup/gid/id/v1",
                json=[shop_game_id],
                params={"key": ITAD_API_KEY},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                response.raise_for_status()
                data = await response.json()

        itad_uuid = data.get(shop_game_id)

        if not itad_uuid:
            logger.warning("[ITAD Lookup] No UUID for %s", shop_game_id)
            return None

        logger.info("[ITAD Lookup] UUID → %s", itad_uuid)
        return itad_uuid

    except asyncio.TimeoutError:
        logger.error("[ITAD Lookup] Timeout for AppID: %s", app_id)
        return None
    except aiohttp.ClientError as e:
        logger.error("[ITAD Lookup] Network error: %s", e)
        return None
    except (ValueError, KeyError) as e:
        logger.error("[ITAD Lookup] Parse error: %s", e)
        return None


# =============================================================================
# SOURCES 2 & 3: ITAD — Best Current Deal + Historical Low (both in BRL)
# =============================================================================

async def get_itad_prices(app_id: str) -> dict | None:
    """
    Fetches the best current promotional deal AND historical low from ITAD.
    Both prices are in BRL (country=BR).

    Internamente executa 3 chamadas HTTP SEQUENCIAIS (dependência de dados):
      1. _get_itad_uuid() — Steam AppID → ITAD UUID (sessão própria)
      2. POST /games/prices/v3?country=BR — current best deal
      3. POST /games/historylow/v1?country=BR — all-time low
    As chamadas 2 e 3 compartilham UMA sessão aiohttp para reutilizar a
    conexão TCP (mais eficiente que criar sessão por chamada).

    IMPORTANT DISTINCTION vs Steam API:
      - Steam price (get_steam_game_info) = official Steam BR price.
      - ITAD best deal (this function) = cheapest price RIGHT NOW across
        all tracked stores (Nuuvem, Fanatical, GreenManGaming, etc.).
      - ITAD historical low = lowest price ever recorded, any store.

    Sentinel value: -1.0 = "data not available" (stored in JSON as -1.0).

    Args:
        app_id (str): Steam AppID to look up prices for.

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
    itad_uuid = await _get_itad_uuid(app_id)
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

    # Sessão compartilhada para as duas chamadas (prices + history).
    # Reutiliza a conexão TCP — mais eficiente que criar uma sessão por chamada.
    async with aiohttp.ClientSession() as session:

        # --- SOURCE 2: Best current deal (no shop filter = best across all stores) ---
        try:
            logger.info("[ITAD Prices] Fetching best current deal for %s", itad_uuid)
            async with session.post(
                f"{ITAD_BASE_URL}/games/prices/v3",
                json=payload,
                params={"key": ITAD_API_KEY, "country": country},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as price_resp:
                price_resp.raise_for_status()
                price_data = await price_resp.json()

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
                            "[ITAD Prices] Best deal: R$ %.2f (%d%% off at %s)",
                            result["best_deal_price"],
                            result["best_deal_cut"],
                            result["best_deal_shop"],
                        )
                else:
                    logger.warning("[ITAD Prices] No current deals found")

        except asyncio.TimeoutError:
            logger.error("[ITAD Prices] Timeout for UUID: %s", itad_uuid)
        except aiohttp.ClientError as e:
            logger.error("[ITAD Prices] Network error: %s", e)
        except (ValueError, KeyError, IndexError) as e:
            logger.error("[ITAD Prices] Parse error: %s", e)

        # --- SOURCE 3: Historical low (all-time, any store) ---
        try:
            logger.info("[ITAD History] Fetching historical low for %s", itad_uuid)
            async with session.post(
                f"{ITAD_BASE_URL}/games/historylow/v1",
                json=payload,
                params={"key": ITAD_API_KEY, "country": country},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as hist_resp:
                hist_resp.raise_for_status()
                hist_data = await hist_resp.json()

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
                            "[ITAD History] Low: R$ %.2f (%d%% off at %s)",
                            result["historical_low"],
                            result["historical_low_cut"],
                            result["historical_low_shop"],
                        )

        except asyncio.TimeoutError:
            logger.error("[ITAD History] Timeout for UUID: %s", itad_uuid)
        except aiohttp.ClientError as e:
            logger.error("[ITAD History] Network error: %s", e)
        except (ValueError, KeyError, IndexError) as e:
            logger.error("[ITAD History] Parse error: %s", e)

    return result
