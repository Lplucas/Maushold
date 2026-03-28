"""
bench_database.py — Benchmark de Performance para database.py

Mede o custo de I/O e lookup com bancos de tamanhos crescentes.
Valida empiricamente a complexidade Big-O das operações:
  - save_database() / load_database(): O(n) — n = tamanho do JSON
  - get_game_by_id(): O(n) I/O + O(1) dict lookup
  - add_interested_user(): O(n) I/O + O(m) scan de duplicata

Uso:
  python tests/benchmarks/bench_database.py

Análise de Performance:
  Tempo: O(n) para todas as operações (dominado pelo I/O de JSON)
  Espaço: O(n) — carrega todo o JSON em memória cada vez
"""

import sys
import os
import json
import asyncio
import time

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import database


# ── Helpers ──────────────────────────────────────────────────────────────────

def generate_test_database(num_games: int, users_per_game: int = 0) -> dict:
    """
    Gera um banco de dados de teste com N jogos.

    Análise de Performance:
      Tempo: O(n * u) — n = num_games, u = users_per_game
      Espaço: O(n * u) — dict em memória

    Usa dict comprehension (implementado em C no CPython) ao invés de
    loop explícito para construção mais rápida.
    """
    games = {
        str(i): {
            "name": f"Game {i}",
            "app_id": str(i),
            "current_price": 50.0 + (i % 100),
            "best_deal_price": 40.0 + (i % 80),
            "best_deal_shop": "Steam",
            "historical_low": 20.0 + (i % 50),
            "interested_users": [
                {"user_id": j, "username": f"user_{j}"}
                for j in range(users_per_game)
            ]
        }
        for i in range(num_games)
    }
    return {"games": games}


async def bench_save_load(sizes: list[int]) -> list[dict]:
    """Benchmark save + load para diferentes tamanhos de banco."""
    results = []

    for n in sizes:
        data = generate_test_database(n)

        # ── Save benchmark ──
        t0 = time.perf_counter()
        await database.save_database(data)
        save_time = time.perf_counter() - t0

        # ── Load benchmark ──
        t0 = time.perf_counter()
        loaded = await database.load_database()
        load_time = time.perf_counter() - t0

        # Verify integrity
        assert len(loaded["games"]) == n

        # File size on disk
        file_size = os.path.getsize(database.DATABASE_FILE)

        results.append({
            "games": n,
            "save_ms": save_time * 1000,
            "load_ms": load_time * 1000,
            "file_kb": file_size / 1024,
        })

    return results


async def bench_lookup(sizes: list[int]) -> list[dict]:
    """
    Benchmark get_game_by_id() para diferentes tamanhos.
    Mede o custo TOTAL (I/O + lookup), não apenas o lookup O(1) do dict.
    """
    results = []

    for n in sizes:
        data = generate_test_database(n)
        await database.save_database(data)

        # Lookup a game that exists (worst-case scenario for I/O: full load)
        target_id = str(n - 1)  # last game

        t0 = time.perf_counter()
        game = await database.get_game_by_id(target_id)
        lookup_time = time.perf_counter() - t0

        assert game is not None

        results.append({
            "games": n,
            "lookup_ms": lookup_time * 1000,
        })

    return results


async def bench_interested_user_scan(user_counts: list[int]) -> list[dict]:
    """
    Benchmark add_interested_user() com lista crescente de interessados.
    Demonstra o custo O(m) da busca linear de duplicata.
    """
    results = []

    for m in user_counts:
        # Create a game with M existing interested users
        data = generate_test_database(1, users_per_game=m)
        await database.save_database(data)

        # Try to add a NEW user (must scan all M existing users first)
        t0 = time.perf_counter()
        result = await database.add_interested_user("0", 99999, "new_user")
        add_time = time.perf_counter() - t0

        assert result == "added"

        results.append({
            "existing_users": m,
            "add_ms": add_time * 1000,
        })

    return results


def print_table(title: str, headers: list[str], rows: list[dict], keys: list[str]):
    """Imprime tabela formatada no terminal."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")

    # Header
    header_line = " | ".join(f"{h:>14}" for h in headers)
    print(f"  {header_line}")
    print(f"  {'-' * len(header_line)}")

    # Rows
    for row in rows:
        values = []
        for k in keys:
            v = row[k]
            if isinstance(v, float):
                values.append(f"{v:>14.3f}")
            else:
                values.append(f"{v:>14}")
        print(f"  {' | '.join(values)}")

    print()


async def main():
    """Executa todos os benchmarks e imprime resultados."""
    # Fix Windows console encoding
    sys.stdout.reconfigure(encoding="utf-8")

    # Use a temporary database file
    original_file = database.DATABASE_FILE
    database.DATABASE_FILE = os.path.join(
        os.path.dirname(__file__), "_bench_temp.json"
    )

    try:
        print("\n🏎️  RatBot Database Benchmarks")
        print("=" * 60)

        # ── Benchmark 1: Save/Load I/O ──
        sizes = [10, 50, 100, 500, 1000, 5000]
        io_results = await bench_save_load(sizes)
        print_table(
            "Benchmark 1: Save/Load I/O — O(n)",
            ["Games (n)", "Save (ms)", "Load (ms)", "File (KB)"],
            io_results,
            ["games", "save_ms", "load_ms", "file_kb"]
        )

        # ── Benchmark 2: Lookup by ID ──
        lookup_results = await bench_lookup(sizes)
        print_table(
            "Benchmark 2: get_game_by_id() — O(n) I/O + O(1) lookup",
            ["Games (n)", "Lookup (ms)"],
            lookup_results,
            ["games", "lookup_ms"]
        )

        # ── Benchmark 3: Interested user scan ──
        user_counts = [0, 10, 50, 100, 500, 1000]
        scan_results = await bench_interested_user_scan(user_counts)
        print_table(
            "Benchmark 3: add_interested_user() — O(m) duplicate scan",
            ["Users (m)", "Add (ms)"],
            scan_results,
            ["existing_users", "add_ms"]
        )

        # ── Summary ──
        print("📊 Análise:")
        print("  • Save/Load escala linearmente com o número de jogos (O(n))")
        print("  • Lookup paga o custo de I/O mesmo para acessar 1 jogo")
        print("  • Duplicate scan em interested_users é O(m) — linear no nº de usuários")
        print()
        print("💡 Recomendação:")
        print("  Para < 1000 jogos, o JSON é perfeitamente adequado.")
        print("  A migração para Supabase (v0.9.0) eliminará o gargalo de I/O")
        print("  transformando lookups em O(1) no servidor de banco de dados.")
        print()

    finally:
        # Cleanup
        temp_file = database.DATABASE_FILE
        database.DATABASE_FILE = original_file
        if os.path.exists(temp_file):
            os.remove(temp_file)


if __name__ == "__main__":
    asyncio.run(main())
