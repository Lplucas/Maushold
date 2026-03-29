"""
test_api.py — Testes unitários para api.py (versão aiohttp)

Cobertura:
  - extract_app_id_from_url(): URLs válidas, inválidas, edge cases (sync)
  - get_steam_game_info(): sucesso, free game, not found, timeout, network error, parse error
  - _get_itad_uuid(): sucesso, API key ausente, UUID null, timeout, network error
  - get_itad_prices(): sucesso completo, deals vazio, histórico ausente

PADRÃO DE MOCKING aiohttp:
  aiohttp usa 'async with ClientSession() as session' + 'async with session.get(...) as response'.
  Para mockar isso, simulamos:
    1. A ClientSession (context manager assíncrono externo)
    2. O método .get()/.post() da sessão (retorna context manager assíncrono interno)
    3. O objeto response (com .json() como AsyncMock e .raise_for_status())

  O helper _make_aiohttp_mock() encapsula toda essa complexidade, retornando
  um mock de ClientSession pronto para uso com @patch("api.aiohttp.ClientSession").
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

import aiohttp
import api

# Marca todos os testes deste módulo como assíncronos.
# Sem isso, testes com 'async def' retornam uma coroutine não-executada
# e passam silenciosamente — um FALSO POSITIVO perigoso.


# =============================================================================
# HELPER: Cria mock de aiohttp.ClientSession para testes
# =============================================================================

def _make_aiohttp_mock(json_data=None, side_effect=None, multi_response=None):
    """
    Cria um mock completo de aiohttp.ClientSession.

    Simula a cadeia: ClientSession() → session.get/post() → response.json()

    Por que esse helper existe:
      Mockar aiohttp requer 3 camadas de context managers assíncronos.
      Sem esse helper, cada teste repetiria ~15 linhas de setup idênticas.

    Args:
        json_data: Dado a ser retornado por response.json() (chamada única).
        side_effect: Exceção ou lista de exceções a levantar em .get()/.post().
        multi_response: Lista de dicts para múltiplas chamadas sequenciais.
                        Cada dict é retornado por response.json() na ordem.

    Returns:
        MagicMock: Mock de ClientSession pronto para @patch("api.aiohttp.ClientSession").
    """
    mock_session_class = MagicMock()
    mock_session = AsyncMock()

    # ClientSession() retorna um context manager assíncrono
    mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_class.return_value.__aexit__ = AsyncMock(return_value=False)

    if side_effect is not None:
        # Exceção ao chamar session.get() ou session.post()
        mock_session.get = MagicMock(side_effect=side_effect)
        mock_session.post = MagicMock(side_effect=side_effect)
    elif multi_response is not None:
        # Múltiplas respostas sequenciais (para get_itad_prices com 2 POSTs)
        mock_responses = []
        for data in multi_response:
            mock_resp = AsyncMock()
            mock_resp.json = AsyncMock(return_value=data)
            mock_resp.raise_for_status = MagicMock()

            # Cada response é um context manager assíncrono
            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_responses.append(mock_ctx)

        mock_session.post = MagicMock(side_effect=mock_responses)
        mock_session.get = MagicMock(side_effect=mock_responses)
    else:
        # Resposta única
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value=json_data)
        mock_response.raise_for_status = MagicMock()

        # session.get() / session.post() retornam um context manager assíncrono
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session.get = MagicMock(return_value=mock_ctx)
        mock_session.post = MagicMock(return_value=mock_ctx)

    return mock_session_class


# =============================================================================
# extract_app_id_from_url() — SYNC (não muda com a migração)
# =============================================================================

class TestExtractAppIdFromUrl:
    """Testes para o parser de URLs da Steam (função síncrona)."""

    def test_full_url_with_game_name(self):
        result = api.extract_app_id_from_url(
            "https://store.steampowered.com/app/1091500/Cyberpunk_2077/"
        )
        assert result == "1091500"

    def test_url_without_game_name(self):
        assert api.extract_app_id_from_url(
            "https://store.steampowered.com/app/1091500"
        ) == "1091500"

    def test_url_without_protocol(self):
        assert api.extract_app_id_from_url(
            "store.steampowered.com/app/1091500"
        ) == "1091500"

    def test_non_steam_url_returns_none(self):
        assert api.extract_app_id_from_url("https://www.google.com") is None

    def test_empty_string_returns_none(self):
        assert api.extract_app_id_from_url("") is None

    def test_plain_number_returns_none(self):
        """Um número solto NÃO é uma URL válida — deve exigir '/app/'."""
        assert api.extract_app_id_from_url("1091500") is None

    def test_partial_path_returns_none(self):
        assert api.extract_app_id_from_url("/app/") is None


# =============================================================================
# get_steam_game_info() — ASYNC
# =============================================================================

@pytest.mark.asyncio
class TestGetSteamGameInfo:
    """Testes para a busca de nome + preço na Steam API (async, aiohttp)."""

    @patch("api.aiohttp.ClientSession")
    async def test_paid_game_success(self, mock_session_class):
        mock_session_class.replace_with = _make_aiohttp_mock(
            json_data={
                "1091500": {
                    "success": True,
                    "data": {
                        "name": "Cyberpunk 2077",
                        "price_overview": {"final": 19990}
                    }
                }
            }
        )
        # Substitui o mock do patch pelo nosso mock configurado
        mock_session_class.return_value = mock_session_class.replace_with.return_value

        result = await api.get_steam_game_info("1091500")
        assert result == {"name": "Cyberpunk 2077", "current_price": 199.9}

    @patch("api.aiohttp.ClientSession")
    async def test_free_game_no_price_overview(self, mock_session_class):
        configured = _make_aiohttp_mock(
            json_data={
                "1091500": {
                    "success": True,
                    "data": {"name": "Free Game"}
                }
            }
        )
        mock_session_class.return_value = configured.return_value

        result = await api.get_steam_game_info("1091500")
        assert result == {"name": "Free Game", "current_price": 0.0}

    @patch("api.aiohttp.ClientSession")
    async def test_app_id_not_found(self, mock_session_class):
        configured = _make_aiohttp_mock(
            json_data={"1091500": {"success": False}}
        )
        mock_session_class.return_value = configured.return_value

        assert await api.get_steam_game_info("1091500") is None

    @patch("api.aiohttp.ClientSession")
    async def test_timeout_returns_none(self, mock_session_class):
        """Timeout de rede deve retornar None sem levantar exceção."""
        # asyncio.TimeoutError substitui requests.exceptions.Timeout
        configured = _make_aiohttp_mock(side_effect=asyncio.TimeoutError())
        mock_session_class.return_value = configured.return_value

        assert await api.get_steam_game_info("1091500") is None

    @patch("api.aiohttp.ClientSession")
    async def test_network_error_returns_none(self, mock_session_class):
        """Erro genérico de rede (DNS, connection refused) deve retornar None."""
        # aiohttp.ClientError substitui requests.exceptions.ConnectionError
        configured = _make_aiohttp_mock(
            side_effect=aiohttp.ClientError("DNS resolution failed")
        )
        mock_session_class.return_value = configured.return_value

        assert await api.get_steam_game_info("1091500") is None

    @patch("api.aiohttp.ClientSession")
    async def test_malformed_json_returns_none(self, mock_session_class):
        """JSON inesperado (ex: response.json() levanta ValueError) → None."""
        configured = _make_aiohttp_mock(
            side_effect=ValueError("No JSON object could be decoded")
        )
        mock_session_class.return_value = configured.return_value

        assert await api.get_steam_game_info("1091500") is None


# =============================================================================
# _get_itad_uuid() — ASYNC
# =============================================================================

@pytest.mark.asyncio
class TestGetItadUuid:
    """Testes para a resolução Steam AppID → ITAD UUID (async, aiohttp)."""

    @patch("api.aiohttp.ClientSession")
    async def test_success(self, mock_session_class):
        api.ITAD_API_KEY = "test_key"

        configured = _make_aiohttp_mock(
            json_data={"app/1091500": "fake-uuid-123"}
        )
        mock_session_class.return_value = configured.return_value

        assert await api._get_itad_uuid("1091500") == "fake-uuid-123"

    async def test_api_key_missing_returns_none(self):
        """Se ITAD_API_KEY é None ou placeholder, retorna None sem fazer request."""
        original_key = api.ITAD_API_KEY
        try:
            api.ITAD_API_KEY = None
            assert await api._get_itad_uuid("1091500") is None

            api.ITAD_API_KEY = "sua_chave_aqui"
            assert await api._get_itad_uuid("1091500") is None
        finally:
            api.ITAD_API_KEY = original_key

    @patch("api.aiohttp.ClientSession")
    async def test_uuid_null_returns_none(self, mock_session_class):
        """ITAD não conhece o jogo → UUID retorna null no JSON."""
        api.ITAD_API_KEY = "test_key"

        configured = _make_aiohttp_mock(
            json_data={"app/1091500": None}
        )
        mock_session_class.return_value = configured.return_value

        assert await api._get_itad_uuid("1091500") is None

    @patch("api.aiohttp.ClientSession")
    async def test_timeout_returns_none(self, mock_session_class):
        api.ITAD_API_KEY = "test_key"
        configured = _make_aiohttp_mock(side_effect=asyncio.TimeoutError())
        mock_session_class.return_value = configured.return_value

        assert await api._get_itad_uuid("1091500") is None

    @patch("api.aiohttp.ClientSession")
    async def test_network_error_returns_none(self, mock_session_class):
        api.ITAD_API_KEY = "test_key"
        configured = _make_aiohttp_mock(
            side_effect=aiohttp.ClientError("Connection refused")
        )
        mock_session_class.return_value = configured.return_value

        assert await api._get_itad_uuid("1091500") is None


# =============================================================================
# get_itad_prices() — ASYNC
# =============================================================================

@pytest.mark.asyncio
class TestGetItadPrices:
    """Testes para busca de melhor deal + histórico de preço via ITAD (async)."""

    @patch("api.aiohttp.ClientSession")
    @patch("api._get_itad_uuid", new_callable=AsyncMock)
    async def test_full_success(self, mock_get_uuid, mock_session_class):
        """Cenário completo: UUID resolve, deals e histórico disponíveis."""
        mock_get_uuid.return_value = "fake-uuid-123"
        api.ITAD_API_KEY = "test_key"

        # get_itad_prices faz 2 POSTs com sessão compartilhada: prices + history
        configured = _make_aiohttp_mock(
            multi_response=[
                # Resposta 1: prices
                [{"deals": [{
                    "price": {"amount": 50.0},
                    "shop": {"name": "Nuuvem"},
                    "cut": 25
                }]}],
                # Resposta 2: history
                [{"low": {
                    "price": {"amount": 40.0},
                    "shop": {"name": "Steam"},
                    "cut": 30
                }}],
            ]
        )
        mock_session_class.return_value = configured.return_value

        result = await api.get_itad_prices("1091500")
        assert result["best_deal_price"] == 50.0
        assert result["best_deal_shop"] == "Nuuvem"
        assert result["best_deal_cut"] == 25
        assert result["historical_low"] == 40.0
        assert result["historical_low_shop"] == "Steam"
        assert result["historical_low_cut"] == 30

    @patch("api._get_itad_uuid", new_callable=AsyncMock)
    async def test_uuid_not_found_returns_none(self, mock_get_uuid):
        """Se UUID não resolve, get_itad_prices() retorna None imediatamente."""
        mock_get_uuid.return_value = None
        assert await api.get_itad_prices("1091500") is None

    @patch("api.aiohttp.ClientSession")
    @patch("api._get_itad_uuid", new_callable=AsyncMock)
    async def test_empty_deals_returns_sentinel(self, mock_get_uuid, mock_session_class):
        """Sem deals disponíveis → best_deal_price fica como -1.0 (sentinela)."""
        mock_get_uuid.return_value = "fake-uuid-123"
        api.ITAD_API_KEY = "test_key"

        configured = _make_aiohttp_mock(
            multi_response=[
                [{"deals": []}],
                [{"low": None}],
            ]
        )
        mock_session_class.return_value = configured.return_value

        result = await api.get_itad_prices("1091500")
        assert result["best_deal_price"] == -1.0
        assert result["best_deal_shop"] == ""
        assert result["historical_low"] == -1.0

    @patch("api.aiohttp.ClientSession")
    @patch("api._get_itad_uuid", new_callable=AsyncMock)
    async def test_history_absent_returns_sentinel(self, mock_get_uuid, mock_session_class):
        """Histórico indisponível mas deals existem → historical_low = -1.0."""
        mock_get_uuid.return_value = "fake-uuid-123"
        api.ITAD_API_KEY = "test_key"

        configured = _make_aiohttp_mock(
            multi_response=[
                [{"deals": [{
                    "price": {"amount": 60.0},
                    "shop": {"name": "GreenManGaming"},
                    "cut": 10
                }]}],
                [],  # empty response
            ]
        )
        mock_session_class.return_value = configured.return_value

        result = await api.get_itad_prices("1091500")
        assert result["best_deal_price"] == 60.0
        assert result["best_deal_shop"] == "GreenManGaming"
        assert result["historical_low"] == -1.0
