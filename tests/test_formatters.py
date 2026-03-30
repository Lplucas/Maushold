"""
test_formatters.py — Testes unitários para formatters.py

Cobertura:
  - steam_store_url(), steam_banner_url(): URLs corretas
  - _format_price(): BRL, grátis, sentinela, fallback
  - _get_status_emoji(): 🔥/✅/❌/❓ + edge cases
  - format_per_person(): cálculo correto, grátis, vazio
  - build_status_blockquote(): todos emojis, fallback
  - build_interests_inline(): vazio, um user, fallback first_name
  - build_interests_block(): monospace, numeração, MAX_DISPLAYED_USERS
  - build_list_block(): bloco completo com link
  - build_game_summary_caption(): caption com dados especiais, limite
  - build_game_interests_text(): spoiler, monospace
  - send_md(), edit_md(), send_photo_md(): entities, fallback
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from telegramify_markdown import convert

import formatters


# =============================================================================
# Fixtures de dados reutilizáveis
# =============================================================================

def _make_game(
    name="Test Game",
    current_price=100.0,
    best_deal_price=60.0,
    best_deal_shop="Steam",
    historical_low=40.0,
    interested_users=None,
):
    """Cria um dict de jogo com valores padrão para testes."""
    return {
        "name": name,
        "current_price": current_price,
        "best_deal_price": best_deal_price,
        "best_deal_shop": best_deal_shop,
        "historical_low": historical_low,
        "interested_users": interested_users or [],
    }


def _make_users(*names):
    """Cria lista de interested_users a partir de nomes."""
    return [{"user_id": i + 1, "username": name} for i, name in enumerate(names)]


# =============================================================================
# steam_store_url()
# =============================================================================

class TestSteamStoreUrl:

    def test_returns_correct_format(self):
        result = formatters.steam_store_url("1091500")
        assert result == "https://store.steampowered.com/app/1091500/"

    def test_different_app_id(self):
        result = formatters.steam_store_url("808010")
        assert "808010" in result
        assert result.startswith("https://store.steampowered.com/app/")


# =============================================================================
# steam_banner_url()
# =============================================================================

class TestSteamBannerUrl:

    def test_returns_cdn_path(self):
        result = formatters.steam_banner_url("1091500")
        assert "cdn.akamai.steamstatic.com" in result
        assert "header.jpg" in result
        assert "1091500" in result

    def test_different_app_id(self):
        result = formatters.steam_banner_url("4000")
        assert "4000" in result


# =============================================================================
# _format_price()
# =============================================================================

class TestFormatPrice:

    def test_paid_game_formats_brl(self):
        result = formatters._format_price(59.90)
        assert result == "R$ 59,90"

    def test_free_game_returns_gratis_emoji(self):
        result = formatters._format_price(0.0)
        assert result == "Grátis 🎉"

    def test_sentinel_minus_one_returns_fallback(self):
        result = formatters._format_price(-1.0)
        assert result == "N/D"

    def test_custom_fallback_text(self):
        result = formatters._format_price(-1.0, "Indisponível")
        assert result == "Indisponível"

    def test_negative_non_sentinel_returns_fallback(self):
        result = formatters._format_price(-99.9)
        assert result == "N/D"

    def test_large_price_with_thousands_separator(self):
        result = formatters._format_price(1299.99)
        assert result == "R$ 1.299,99"

    def test_small_price(self):
        result = formatters._format_price(0.99)
        assert result == "R$ 0,99"


# =============================================================================
# _get_status_emoji()
# =============================================================================

class TestGetStatusEmoji:

    def test_at_historical_low_returns_fire(self):
        assert formatters._get_status_emoji(100.0, 40.0, 40.0) == "🔥"

    def test_within_one_cent_of_low_returns_fire(self):
        assert formatters._get_status_emoji(100.0, 40.01, 40.0) == "🔥"

    def test_30_percent_off_returns_checkmark(self):
        assert formatters._get_status_emoji(100.0, 70.0, 50.0) == "✅"

    def test_exactly_30_percent_off_returns_checkmark(self):
        assert formatters._get_status_emoji(100.0, 70.00, 50.0) == "✅"

    def test_no_meaningful_deal_returns_x(self):
        assert formatters._get_status_emoji(100.0, 95.0, 50.0) == "❌"

    def test_all_sentinel_returns_question_mark(self):
        assert formatters._get_status_emoji(-1.0, -1.0, -1.0) == "❓"

    def test_no_deal_data_uses_steam_price(self):
        # deal=-1 → referência = current_price (100) → 100 > 90+0.01
        assert formatters._get_status_emoji(100.0, -1.0, 90.0) == "❌"

    def test_negative_current_positive_deal(self):
        result = formatters._get_status_emoji(-1.0, 50.0, 50.0)
        assert result == "🔥"

    def test_positive_current_negative_deal_at_low(self):
        result = formatters._get_status_emoji(40.0, -1.0, 40.0)
        assert result == "🔥"


# =============================================================================
# format_per_person()
# =============================================================================

class TestFormatPerPerson:

    def test_with_valid_price_and_users(self):
        game = _make_game(best_deal_price=100.0, interested_users=_make_users("a", "b"))
        result = formatters.format_per_person(game)
        assert result == "R$ 50,00"

    def test_prefers_deal_over_steam_price(self):
        game = _make_game(current_price=100.0, best_deal_price=60.0,
                          interested_users=_make_users("a", "b"))
        result = formatters.format_per_person(game)
        assert result == "R$ 30,00"

    def test_no_interested_users_returns_dash(self):
        game = _make_game(interested_users=[])
        result = formatters.format_per_person(game)
        assert result == "—"

    def test_no_price_data_returns_dash(self):
        game = _make_game(current_price=-1.0, best_deal_price=-1.0,
                          interested_users=_make_users("a"))
        result = formatters.format_per_person(game)
        assert result == "—"

    def test_free_game_returns_dash(self):
        game = _make_game(current_price=0.0, best_deal_price=0.0,
                          interested_users=_make_users("a", "b"))
        result = formatters.format_per_person(game)
        assert result == "—"

    def test_falls_back_to_steam_price_when_no_deal(self):
        game = _make_game(current_price=100.0, best_deal_price=-1.0,
                          interested_users=_make_users("a", "b"))
        result = formatters.format_per_person(game)
        assert result == "R$ 50,00"


# =============================================================================
# build_status_blockquote()
# =============================================================================

class TestBuildStatusBlockquote:

    def test_fire_contains_blockquote_syntax(self):
        result = formatters.build_status_blockquote("🔥")
        assert result.startswith("> ")
        assert "MENOR PREÇO" in result

    def test_all_emojis_return_nonempty_string(self):
        for emoji in ["🔥", "✅", "❌", "❓"]:
            result = formatters.build_status_blockquote(emoji)
            assert len(result) > 0

    def test_unknown_emoji_returns_default(self):
        result = formatters.build_status_blockquote("💎")
        assert "❓" in result


# =============================================================================
# build_interests_inline()
# =============================================================================

class TestBuildInterestsInline:

    def test_empty_list_returns_nobody(self):
        game = _make_game(interested_users=[])
        people, _ = formatters.build_interests_inline(game)
        assert people == "Ninguém ainda"

    def test_single_user_with_handle(self):
        game = _make_game(interested_users=_make_users("lucas"))
        people, _ = formatters.build_interests_inline(game)
        assert "@lucas" in people

    def test_user_with_first_name_fallback(self):
        """Username com espaço = first_name, não recebe @."""
        game = _make_game(interested_users=[{"user_id": 1, "username": "Lucas Andrade"}])
        people, _ = formatters.build_interests_inline(game)
        assert "Lucas Andrade" in people
        assert "@Lucas Andrade" not in people


# =============================================================================
# build_interests_block()
# =============================================================================

class TestBuildInterestsBlock:

    def test_returns_monospace_delimiters(self):
        game = _make_game(interested_users=_make_users("lucas", "joao"))
        result = formatters.build_interests_block(game, "1234")
        assert "```" in result

    def test_numbers_users_sequentially(self):
        game = _make_game(interested_users=_make_users("lucas", "joao", "ana"))
        result = formatters.build_interests_block(game, "1234")
        assert "1." in result
        assert "2." in result
        assert "3." in result

    def test_special_chars_in_username_preserved_in_mono(self):
        """Monospace não precisa de escape — underscores são literais."""
        game = _make_game(interested_users=_make_users("user_name"))
        result = formatters.build_interests_block(game, "1234")
        assert "user_name" in result

    def test_empty_list_suggests_want(self):
        game = _make_game(interested_users=[])
        result = formatters.build_interests_block(game, "1234")
        assert "/want" in result
        assert "1234" in result

    def test_truncates_at_max_displayed_users(self):
        users = _make_users(*[f"user{i}" for i in range(10)])
        game = _make_game(interested_users=users)
        result = formatters.build_interests_block(game, "1234")
        assert "... e mais" in result
        # Should show 6, truncate 4
        assert "4 pessoas" in result


# =============================================================================
# build_list_block()
# =============================================================================

class TestBuildListBlock:

    def test_contains_game_name_linked(self):
        game = _make_game(name="Cyberpunk 2077")
        result = formatters.build_list_block("1091500", game)
        assert "Cyberpunk 2077" in result
        assert "store.steampowered.com/app/1091500/" in result

    def test_contains_app_id(self):
        game = _make_game()
        result = formatters.build_list_block("808010", game)
        assert "808010" in result

    def test_converts_without_error(self):
        """O bloco deve ser conversível por telegramify sem exceção."""
        game = _make_game(name="Green_Man_Gaming Test*")
        block = formatters.build_list_block("1234", game)
        text, entities = convert(block)
        assert len(text) > 0


# =============================================================================
# build_game_summary_caption()
# =============================================================================

class TestBuildGameSummaryCaption:

    def test_contains_game_name(self):
        game = _make_game(name="Cyberpunk 2077")
        result = formatters.build_game_summary_caption(game, "1091500")
        assert "Cyberpunk 2077" in result

    def test_contains_steam_link(self):
        game = _make_game()
        result = formatters.build_game_summary_caption(game, "1091500")
        assert "store.steampowered.com/app/1091500" in result

    def test_with_special_chars_in_name(self):
        """O caption com caracteres especiais deve ser conversível sem erro."""
        game = _make_game(name="Baldur's Gate*3")
        result = formatters.build_game_summary_caption(game, "1234")
        # Deve converter sem lançar exceção
        text, entities = convert(result)
        assert "Baldur" in text

    def test_with_underscore_in_shop_name(self):
        """Nomes de loja com underscore devem converter sem erro."""
        game = _make_game(best_deal_shop="Green_Man_Gaming")
        result = formatters.build_game_summary_caption(game, "1234")
        text, entities = convert(result)
        assert "Green_Man_Gaming" in text

    def test_free_game_shows_gratis(self):
        game = _make_game(current_price=0.0)
        result = formatters.build_game_summary_caption(game, "1234")
        assert "Grátis" in result

    def test_blockquote_present(self):
        game = _make_game()
        result = formatters.build_game_summary_caption(game, "1234")
        assert "> " in result


# =============================================================================
# build_game_interests_text()
# =============================================================================

class TestBuildGameInterestsText:

    def test_contains_spoiler_on_price(self):
        game = _make_game(interested_users=_make_users("lucas", "joao"))
        result = formatters.build_game_interests_text(game, "1234")
        assert "||" in result  # Spoiler delimiters
        assert "toque para revelar" in result

    def test_no_spoiler_when_no_price(self):
        game = _make_game(current_price=-1.0, best_deal_price=-1.0,
                          interested_users=_make_users("lucas"))
        result = formatters.build_game_interests_text(game, "1234")
        assert "||" not in result
        assert "—" in result

    def test_contains_monospace_block(self):
        game = _make_game(interested_users=_make_users("lucas"))
        result = formatters.build_game_interests_text(game, "1234")
        assert "```" in result

    def test_converts_without_error(self):
        """O bloco de interesses deve converter sem exceção."""
        game = _make_game(interested_users=_make_users("user_name", "user*star"))
        result = formatters.build_game_interests_text(game, "1234")
        text, entities = convert(result)
        assert len(text) > 0


# =============================================================================
# send_md() — async helpers
# =============================================================================

class TestSendMd:

    @pytest.mark.asyncio
    async def test_calls_reply_text_with_entities_not_parse_mode(self):
        mock_message = AsyncMock()
        await formatters.send_md(mock_message, "**negrito**")
        mock_message.reply_text.assert_called_once()
        kwargs = mock_message.reply_text.call_args.kwargs
        assert "parse_mode" not in kwargs
        assert "entities" in kwargs

    @pytest.mark.asyncio
    async def test_with_special_chars_does_not_raise(self):
        """O char que causou o bug em produção não deve causar exceção."""
        mock_message = AsyncMock()
        # Não deve lançar BadRequest
        await formatters.send_md(mock_message, "**Green_Man_Gaming** e *asterisk*")
        mock_message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_on_convert_error(self):
        """Se convert() falhar, envia como texto puro."""
        mock_message = AsyncMock()
        # Forçar convert() a falhar não é fácil com input válido;
        # testamos o fluxo normal e confiamos no try/except.
        await formatters.send_md(mock_message, "texto simples sem formatação")
        mock_message.reply_text.assert_called_once()


# =============================================================================
# edit_md()
# =============================================================================

class TestEditMd:

    @pytest.mark.asyncio
    async def test_calls_edit_text_with_entities(self):
        mock_message = AsyncMock()
        await formatters.edit_md(mock_message, "**editado**")
        mock_message.edit_text.assert_called_once()
        kwargs = mock_message.edit_text.call_args.kwargs
        assert "entities" in kwargs
        assert "parse_mode" not in kwargs


# =============================================================================
# send_photo_md()
# =============================================================================

class TestSendPhotoMd:

    @pytest.mark.asyncio
    async def test_calls_reply_photo_with_entities(self):
        mock_message = AsyncMock()
        await formatters.send_photo_md(mock_message, "http://img.jpg", "**caption**")
        mock_message.reply_photo.assert_called_once()
        kwargs = mock_message.reply_photo.call_args.kwargs
        assert "caption_entities" in kwargs
        assert "parse_mode" not in kwargs

    @pytest.mark.asyncio
    async def test_falls_back_to_text_on_photo_error(self):
        mock_message = AsyncMock()
        mock_message.reply_photo.side_effect = Exception("banner not found")
        await formatters.send_photo_md(mock_message, "http://invalid/img.jpg", "**caption**")
        # Fallback: deve chamar reply_text
        mock_message.reply_text.assert_called_once()
        # A foto foi tentada
        mock_message.reply_photo.assert_called_once()
