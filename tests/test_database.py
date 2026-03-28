"""
test_database.py — Testes unitários para database.py

Cobertura:
  - load_database(): arquivo inexistente, round-trip, JSON corrupto
  - save_database(): escrita e validação
  - add_game(): novo jogo, duplicata, verificação de todos os campos
  - get_all_games(): retorno normal, chave "games" ausente
  - get_game_by_id(): encontrado, não encontrado
  - add_interested_user(): adicionado, duplicata, jogo não encontrado, username None
"""

import pytest
import os
import json
import asyncio
import database

# pytest-asyncio needs this to know we are using async tests
pytestmark = pytest.mark.asyncio


@pytest.fixture
def temp_db_file(tmp_path):
    """Redireciona DATABASE_FILE para arquivo temporário durante o teste."""
    test_db = tmp_path / "test_database.json"
    original_db_file = database.DATABASE_FILE
    # Create a fresh lock for each test to avoid sharing state between tests
    original_lock = database.db_lock
    database.db_lock = asyncio.Lock()
    database.DATABASE_FILE = str(test_db)
    yield str(test_db)
    database.DATABASE_FILE = original_db_file
    database.db_lock = original_lock


# =============================================================================
# load_database()
# =============================================================================

class TestLoadDatabase:

    async def test_file_not_exists_returns_empty(self, temp_db_file):
        """Arquivo inexistente → retorna estrutura vazia sem criar arquivo."""
        data = await database.load_database()
        assert data == {"games": {}}
        assert not os.path.exists(temp_db_file)

    async def test_round_trip_save_and_load(self, temp_db_file):
        """Salva dados → carrega → verifica igualdade (integridade de I/O)."""
        test_data = {"games": {"123": {"name": "Test Game"}}}
        await database.save_database(test_data)

        assert os.path.exists(temp_db_file)

        # Verify file content directly (bypass our function)
        with open(temp_db_file, "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert saved == test_data

        # Verify via our load function
        loaded = await database.load_database()
        assert loaded == test_data

    async def test_corrupted_json_returns_empty(self, temp_db_file):
        """JSON inválido no arquivo → retorna banco vazio (resiliência)."""
        with open(temp_db_file, "w", encoding="utf-8") as f:
            f.write("{invalid json content!!!")

        data = await database.load_database()
        assert data == {"games": {}}


# =============================================================================
# save_database()
# =============================================================================

class TestSaveDatabase:

    async def test_creates_file(self, temp_db_file):
        """save_database() cria o arquivo se ele não existe."""
        assert not os.path.exists(temp_db_file)
        await database.save_database({"games": {}})
        assert os.path.exists(temp_db_file)

    async def test_preserves_utf8_characters(self, temp_db_file):
        """Caracteres especiais (acentos) são preservados com ensure_ascii=False."""
        test_data = {"games": {"1": {"name": "Ação Épica — Edição Especial"}}}
        await database.save_database(test_data)

        with open(temp_db_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert "Ação" in content
        assert "Épica" in content


# =============================================================================
# add_game()
# =============================================================================

class TestAddGame:

    async def test_add_new_game_returns_true(self, temp_db_file):
        """Adicionar jogo novo → retorna True e dados estão no banco."""
        added = await database.add_game("100", "Game 1", 50.0, 40.0, "Nuuvem", 10.0)
        assert added is True

        data = await database.load_database()
        assert "100" in data["games"]
        assert data["games"]["100"]["name"] == "Game 1"
        assert data["games"]["100"]["current_price"] == 50.0

    async def test_add_duplicate_returns_false(self, temp_db_file):
        """Adicionar jogo que já existe → retorna False, não sobrescreve."""
        await database.add_game("100", "Game 1", 50.0, 40.0, "", 10.0)
        added_again = await database.add_game("100", "Game 1 (Dup)", 99.0, 99.0, "", 99.0)
        assert added_again is False

        # Verify original data preserved
        data = await database.load_database()
        assert data["games"]["100"]["name"] == "Game 1"
        assert data["games"]["100"]["current_price"] == 50.0

    async def test_all_fields_stored_correctly(self, temp_db_file):
        """Verifica que TODOS os campos são armazenados corretamente."""
        await database.add_game("200", "Full Game", 99.99, 79.99, "Steam", 49.99)

        data = await database.load_database()
        game = data["games"]["200"]

        assert game["name"] == "Full Game"
        assert game["app_id"] == "200"
        assert game["current_price"] == 99.99
        assert game["best_deal_price"] == 79.99
        assert game["best_deal_shop"] == "Steam"
        assert game["historical_low"] == 49.99
        assert game["interested_users"] == []


# =============================================================================
# get_all_games()
# =============================================================================

class TestGetAllGames:

    async def test_returns_all_games(self, temp_db_file):
        """Retorna dict de todos os jogos."""
        await database.save_database({"games": {"1": {"name": "A"}, "2": {"name": "B"}}})
        games = await database.get_all_games()
        assert len(games) == 2
        assert "1" in games
        assert "2" in games

    async def test_missing_games_key_returns_empty(self, temp_db_file):
        """Arquivo sem chave 'games' → retorna {} (guard do .get())."""
        await database.save_database({"other_key": "value"})
        games = await database.get_all_games()
        assert games == {}


# =============================================================================
# get_game_by_id()
# =============================================================================

class TestGetGameById:

    async def test_found(self, temp_db_file):
        await database.save_database({"games": {"999": {"name": "XYZ"}}})
        game = await database.get_game_by_id("999")
        assert game["name"] == "XYZ"

    async def test_not_found(self, temp_db_file):
        await database.save_database({"games": {"999": {"name": "XYZ"}}})
        no_game = await database.get_game_by_id("000")
        assert no_game is None


# =============================================================================
# add_interested_user()
# =============================================================================

class TestAddInterestedUser:

    async def test_add_user_success(self, temp_db_file):
        """Adicionar usuário a jogo existente → 'added'."""
        await database.add_game("100", "Game 1", 50.0, 40.0, "", 10.0)
        result = await database.add_interested_user("100", 12345, "lucas")
        assert result == "added"

        game = await database.get_game_by_id("100")
        assert len(game["interested_users"]) == 1
        assert game["interested_users"][0]["user_id"] == 12345
        assert game["interested_users"][0]["username"] == "lucas"

    async def test_duplicate_user(self, temp_db_file):
        """Mesmo usuário duas vezes → 'duplicate'."""
        await database.add_game("100", "Game 1", 50.0, 40.0, "", 10.0)
        await database.add_interested_user("100", 12345, "lucas")
        result = await database.add_interested_user("100", 12345, "lucas")
        assert result == "duplicate"

    async def test_game_not_found(self, temp_db_file):
        """Jogo inexistente → 'not_found'."""
        result = await database.add_interested_user("999", 12345, "lucas")
        assert result == "not_found"

    async def test_username_none_fallback(self, temp_db_file):
        """Username None → armazenado como 'unknown'."""
        await database.add_game("100", "Game 1", 50.0, 40.0, "", 10.0)
        result = await database.add_interested_user("100", 12345, None)
        assert result == "added"

        game = await database.get_game_by_id("100")
        assert game["interested_users"][0]["username"] == "unknown"

    async def test_multiple_users(self, temp_db_file):
        """Múltiplos usuários diferentes → todos adicionados corretamente."""
        await database.add_game("100", "Game 1", 50.0, 40.0, "", 10.0)
        await database.add_interested_user("100", 111, "user_a")
        await database.add_interested_user("100", 222, "user_b")
        await database.add_interested_user("100", 333, "user_c")

        game = await database.get_game_by_id("100")
        assert len(game["interested_users"]) == 3
        user_ids = {u["user_id"] for u in game["interested_users"]}
        assert user_ids == {111, 222, 333}
