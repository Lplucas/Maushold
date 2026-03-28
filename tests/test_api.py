"""
test_api.py — Testes unitários para api.py

Cobertura:
  - extract_app_id_from_url(): URLs válidas, inválidas, edge cases
  - get_steam_game_info(): sucesso, free game, not found, timeout, network error, parse error
  - _get_itad_uuid(): sucesso, API key ausente, UUID null, timeout, network error
  - get_itad_prices(): sucesso completo, deals vazio, histórico ausente
"""

import pytest
from unittest.mock import patch, MagicMock
import requests
import api


# =============================================================================
# extract_app_id_from_url()
# =============================================================================

class TestExtractAppIdFromUrl:
    """Testes para o parser de URLs da Steam."""

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
# get_steam_game_info()
# =============================================================================

class TestGetSteamGameInfo:
    """Testes para a busca de nome + preço na Steam API."""

    @patch("api.requests.get")
    def test_paid_game_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "1091500": {
                "success": True,
                "data": {
                    "name": "Cyberpunk 2077",
                    "price_overview": {"final": 19990}
                }
            }
        }
        mock_get.return_value = mock_response

        result = api.get_steam_game_info("1091500")
        assert result == {"name": "Cyberpunk 2077", "current_price": 199.9}

    @patch("api.requests.get")
    def test_free_game_no_price_overview(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "1091500": {
                "success": True,
                "data": {"name": "Free Game"}
            }
        }
        mock_get.return_value = mock_response

        result = api.get_steam_game_info("1091500")
        assert result == {"name": "Free Game", "current_price": 0.0}

    @patch("api.requests.get")
    def test_app_id_not_found(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "1091500": {"success": False}
        }
        mock_get.return_value = mock_response

        assert api.get_steam_game_info("1091500") is None

    @patch("api.requests.get")
    def test_timeout_returns_none(self, mock_get):
        """Timeout de rede deve retornar None sem levantar exceção."""
        mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")
        assert api.get_steam_game_info("1091500") is None

    @patch("api.requests.get")
    def test_network_error_returns_none(self, mock_get):
        """Erro genérico de rede (DNS, connection refused) deve retornar None."""
        mock_get.side_effect = requests.exceptions.ConnectionError("DNS resolution failed")
        assert api.get_steam_game_info("1091500") is None

    @patch("api.requests.get")
    def test_malformed_json_returns_none(self, mock_get):
        """JSON inesperado (ex: response.json() levanta ValueError) → None."""
        mock_response = MagicMock()
        mock_response.json.side_effect = ValueError("No JSON object could be decoded")
        mock_get.return_value = mock_response

        assert api.get_steam_game_info("1091500") is None


# =============================================================================
# _get_itad_uuid()
# =============================================================================

class TestGetItadUuid:
    """Testes para a resolução Steam AppID → ITAD UUID."""

    @patch("api.requests.post")
    def test_success(self, mock_post):
        api.ITAD_API_KEY = "test_key"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "app/1091500": "fake-uuid-123"
        }
        mock_post.return_value = mock_response

        assert api._get_itad_uuid("1091500") == "fake-uuid-123"

    def test_api_key_missing_returns_none(self):
        """Se ITAD_API_KEY é None ou placeholder, retorna None sem fazer request."""
        original_key = api.ITAD_API_KEY
        try:
            api.ITAD_API_KEY = None
            assert api._get_itad_uuid("1091500") is None

            api.ITAD_API_KEY = "sua_chave_aqui"
            assert api._get_itad_uuid("1091500") is None
        finally:
            api.ITAD_API_KEY = original_key

    @patch("api.requests.post")
    def test_uuid_null_returns_none(self, mock_post):
        """ITAD não conhece o jogo → UUID retorna null no JSON."""
        api.ITAD_API_KEY = "test_key"

        mock_response = MagicMock()
        mock_response.json.return_value = {"app/1091500": None}
        mock_post.return_value = mock_response

        assert api._get_itad_uuid("1091500") is None

    @patch("api.requests.post")
    def test_timeout_returns_none(self, mock_post):
        api.ITAD_API_KEY = "test_key"
        mock_post.side_effect = requests.exceptions.Timeout("Timed out")
        assert api._get_itad_uuid("1091500") is None

    @patch("api.requests.post")
    def test_network_error_returns_none(self, mock_post):
        api.ITAD_API_KEY = "test_key"
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")
        assert api._get_itad_uuid("1091500") is None


# =============================================================================
# get_itad_prices()
# =============================================================================

class TestGetItadPrices:
    """Testes para busca de melhor deal + histórico de preço via ITAD."""

    @patch("api.requests.post")
    @patch("api._get_itad_uuid")
    def test_full_success(self, mock_get_uuid, mock_post):
        """Cenário completo: UUID resolve, deals e histórico disponíveis."""
        mock_get_uuid.return_value = "fake-uuid-123"
        api.ITAD_API_KEY = "test_key"

        mock_resp_prices = MagicMock()
        mock_resp_prices.json.return_value = [{
            "deals": [{
                "price": {"amount": 50.0},
                "shop": {"name": "Nuuvem"},
                "cut": 25
            }]
        }]

        mock_resp_history = MagicMock()
        mock_resp_history.json.return_value = [{
            "low": {
                "price": {"amount": 40.0},
                "shop": {"name": "Steam"},
                "cut": 30
            }
        }]

        mock_post.side_effect = [mock_resp_prices, mock_resp_history]

        result = api.get_itad_prices("1091500")
        assert result["best_deal_price"] == 50.0
        assert result["best_deal_shop"] == "Nuuvem"
        assert result["best_deal_cut"] == 25
        assert result["historical_low"] == 40.0
        assert result["historical_low_shop"] == "Steam"
        assert result["historical_low_cut"] == 30

    @patch("api._get_itad_uuid")
    def test_uuid_not_found_returns_none(self, mock_get_uuid):
        """Se UUID não resolve, get_itad_prices() retorna None imediatamente."""
        mock_get_uuid.return_value = None
        assert api.get_itad_prices("1091500") is None

    @patch("api.requests.post")
    @patch("api._get_itad_uuid")
    def test_empty_deals_returns_sentinel(self, mock_get_uuid, mock_post):
        """Sem deals disponíveis → best_deal_price fica como -1.0 (sentinela)."""
        mock_get_uuid.return_value = "fake-uuid-123"
        api.ITAD_API_KEY = "test_key"

        mock_resp_prices = MagicMock()
        mock_resp_prices.json.return_value = [{"deals": []}]

        mock_resp_history = MagicMock()
        mock_resp_history.json.return_value = [{"low": None}]

        mock_post.side_effect = [mock_resp_prices, mock_resp_history]

        result = api.get_itad_prices("1091500")
        assert result["best_deal_price"] == -1.0
        assert result["best_deal_shop"] == ""
        assert result["historical_low"] == -1.0

    @patch("api.requests.post")
    @patch("api._get_itad_uuid")
    def test_history_absent_returns_sentinel(self, mock_get_uuid, mock_post):
        """Histórico indisponível mas deals existem → historical_low = -1.0."""
        mock_get_uuid.return_value = "fake-uuid-123"
        api.ITAD_API_KEY = "test_key"

        mock_resp_prices = MagicMock()
        mock_resp_prices.json.return_value = [{
            "deals": [{
                "price": {"amount": 60.0},
                "shop": {"name": "GreenManGaming"},
                "cut": 10
            }]
        }]

        mock_resp_history = MagicMock()
        mock_resp_history.json.return_value = []  # empty response

        mock_post.side_effect = [mock_resp_prices, mock_resp_history]

        result = api.get_itad_prices("1091500")
        assert result["best_deal_price"] == 60.0
        assert result["best_deal_shop"] == "GreenManGaming"
        assert result["historical_low"] == -1.0
