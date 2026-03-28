"""
test_bot.py — Testes unitários para bot.py

Cobertura:
  - _format_price(): preço normal, grátis, sentinela, fallback custom
  - _get_status_emoji(): todos cenários (🔥 / ✅ / ❌ / ❓) + edge cases
  - start_command(): verifica nome e boas-vindas
  - help_command(): verifica comandos listados
  - add_command(): sem argumento, URL inválida, jogo duplicado
  - want_command(): sem argumento, input inválido
  - game_command(): sem argumento, URL Steam, não-numérico, AppID não encontrado
  - list_command(): banco vazio
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import bot


# =============================================================================
# _format_price() — Helper de formatação de preço
# =============================================================================

class TestFormatPrice:

    def test_normal_price(self):
        assert bot._format_price(100.50) == "R$ 100.50"

    def test_zero_price(self):
        assert bot._format_price(0.0) == "R$ 0.00"

    def test_sentinel_default_fallback(self):
        assert bot._format_price(-1.0) == "N/D"

    def test_sentinel_custom_fallback(self):
        assert bot._format_price(-1.0, "Indisponível") == "Indisponível"

    def test_small_price(self):
        assert bot._format_price(0.99) == "R$ 0.99"

    def test_large_price(self):
        assert bot._format_price(999.99) == "R$ 999.99"


# =============================================================================
# _get_status_emoji() — Helper de avaliação de deal
# =============================================================================

class TestGetStatusEmoji:

    def test_no_usable_data(self):
        """Sem dados de preço → ❓"""
        assert bot._get_status_emoji(-1.0, -1.0, -1.0) == "❓"

    def test_at_historical_low(self):
        """Preço atual == mínimo histórico → 🔥"""
        assert bot._get_status_emoji(100.0, 40.0, 40.0) == "🔥"

    def test_within_tolerance_of_historical_low(self):
        """Dentro de R$0.01 do mínimo → 🔥"""
        assert bot._get_status_emoji(100.0, 40.01, 40.0) == "🔥"

    def test_solid_discount_30_percent(self):
        """Exatamente 30% off → ✅"""
        assert bot._get_status_emoji(100.0, 70.0, 40.0) == "✅"

    def test_solid_discount_50_percent(self):
        """50% off → ✅"""
        assert bot._get_status_emoji(100.0, 50.0, 20.0) == "✅"

    def test_bad_deal_5_percent(self):
        """Apenas 5% off → ❌"""
        assert bot._get_status_emoji(100.0, 95.0, 40.0) == "❌"

    def test_no_discount(self):
        """0% off → ❌"""
        assert bot._get_status_emoji(100.0, 100.0, 40.0) == "❌"

    def test_negative_current_positive_deal(self):
        """current_price < 0 mas best_deal >= 0 → não é ❓ (tem dados parciais)."""
        # reference_price = best_deal, historical_low check applies
        result = bot._get_status_emoji(-1.0, 50.0, 50.0)
        assert result == "🔥"  # best_deal == historical_low

    def test_positive_current_negative_deal(self):
        """current_price > 0, best_deal = -1.0, com histórico."""
        # reference_price falls back to current_price
        result = bot._get_status_emoji(40.0, -1.0, 40.0)
        assert result == "🔥"  # current == historical_low


# =============================================================================
# start_command()
# =============================================================================

class TestStartCommand:

    @pytest.mark.asyncio
    async def test_sends_welcome_with_username(self, mock_update, mock_context):
        await bot.start_command(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        args, kwargs = mock_update.message.reply_text.call_args
        assert "Lucas" in args[0]
        assert "bem-vindo" in args[0].lower() or "Bem-vindo" in args[0]


# =============================================================================
# help_command()
# =============================================================================

class TestHelpCommand:

    @pytest.mark.asyncio
    async def test_lists_all_commands(self, mock_update, mock_context):
        await bot.help_command(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        args, _ = mock_update.message.reply_text.call_args
        message_text = args[0]
        assert "/add" in message_text
        assert "/want" in message_text
        assert "/list" in message_text
        assert "/game" in message_text


# =============================================================================
# add_command() — Testes de validação de input
# =============================================================================

class TestAddCommand:

    @pytest.mark.asyncio
    async def test_no_args_shows_usage(self, mock_update, mock_context):
        """Sem argumento → mensagem de instrução."""
        mock_context.args = []
        await bot.add_command(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        args, _ = mock_update.message.reply_text.call_args
        assert "URL" in args[0] or "url" in args[0].lower()

    @pytest.mark.asyncio
    async def test_invalid_url_shows_error(self, mock_update, mock_context):
        """URL não-Steam → erro com exemplo de uso correto."""
        mock_context.args = ["https://www.google.com"]
        await bot.add_command(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        args, _ = mock_update.message.reply_text.call_args
        assert "inválido" in args[0].lower() or "❌" in args[0]


# =============================================================================
# want_command() — Testes de validação de input
# =============================================================================

class TestWantCommand:

    @pytest.mark.asyncio
    async def test_no_args_shows_usage(self, mock_update, mock_context):
        """Sem argumento → instruções com exemplos dos dois modos."""
        mock_context.args = []
        await bot.want_command(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        args, _ = mock_update.message.reply_text.call_args
        assert "/want" in args[0]

    @pytest.mark.asyncio
    async def test_invalid_input_shows_error(self, mock_update, mock_context):
        """Input que não é URL nem número → erro."""
        mock_context.args = ["abc_invalid"]
        await bot.want_command(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        args, _ = mock_update.message.reply_text.call_args
        assert "❌" in args[0]


# =============================================================================
# game_command() — Testes de validação e edge cases
# =============================================================================

class TestGameCommand:

    @pytest.mark.asyncio
    async def test_no_args_shows_usage(self, mock_update, mock_context):
        """Sem argumento → instruções de uso."""
        mock_context.args = []
        await bot.game_command(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        args, _ = mock_update.message.reply_text.call_args
        assert "AppID" in args[0]

    @pytest.mark.asyncio
    async def test_steam_url_suggests_appid(self, mock_update, mock_context):
        """URL da Steam ao invés de AppID → redireciona gentilmente."""
        mock_context.args = ["https://store.steampowered.com/app/1091500/"]
        await bot.game_command(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        args, _ = mock_update.message.reply_text.call_args
        assert "1091500" in args[0]
        assert "/game" in args[0]

    @pytest.mark.asyncio
    async def test_non_numeric_input_shows_error(self, mock_update, mock_context):
        """Input não numérico → erro com exemplo."""
        mock_context.args = ["cyberpunk"]
        await bot.game_command(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        args, _ = mock_update.message.reply_text.call_args
        assert "❌" in args[0]

    @pytest.mark.asyncio
    @patch("bot.database.get_game_by_id", new_callable=AsyncMock)
    async def test_appid_not_found_suggests_add(self, mock_get_game, mock_update, mock_context):
        """AppID que não existe no banco → sugere /add."""
        mock_get_game.return_value = None
        mock_context.args = ["9999999"]

        await bot.game_command(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        args, _ = mock_update.message.reply_text.call_args
        assert "/add" in args[0]
        assert "9999999" in args[0]


# =============================================================================
# list_command() — Testes de estado vazio
# =============================================================================

class TestListCommand:

    @pytest.mark.asyncio
    @patch("bot.database.get_all_games", new_callable=AsyncMock)
    async def test_empty_database_shows_onboarding(self, mock_get_games, mock_update, mock_context):
        """Banco vazio → mensagem amigável sugerindo /add."""
        mock_get_games.return_value = {}

        await bot.list_command(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        args, _ = mock_update.message.reply_text.call_args
        assert "vazia" in args[0].lower() or "📭" in args[0]
        assert "/add" in args[0]
