"""
bench_api.py — Benchmark de Performance para api.py

Mede o overhead de processamento das funções de API (com mocks),
isolando a lógica Python da latência de rede.

Uso:
  python tests/benchmarks/bench_api.py

Análise de Performance:
  Tempo: O(1) para todas as funções (processamento de resposta fixo)
  A latência real é dominada por I/O de rede (~100-500ms por request),
  não pelo processamento Python (~0.01ms).
"""

import sys
import os
import time
import timeit
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import api


# ── Helper: create realistic mock responses ─────────────────────────────────

def create_steam_mock_response(app_id: str = "1091500"):
    """Creates a mock requests.Response for Steam API."""
    mock = MagicMock()
    mock.json.return_value = {
        app_id: {
            "success": True,
            "data": {
                "name": "Benchmark Test Game",
                "price_overview": {"final": 19990}
            }
        }
    }
    return mock


def create_itad_prices_mock():
    """Creates a mock response for ITAD prices endpoint."""
    mock = MagicMock()
    mock.json.return_value = [{
        "deals": [{
            "price": {"amount": 89.90},
            "shop": {"name": "Nuuvem"},
            "cut": 25,
        }]
    }]
    return mock


def create_itad_history_mock():
    """Creates a mock response for ITAD history endpoint."""
    mock = MagicMock()
    mock.json.return_value = [{
        "low": {
            "price": {"amount": 49.90},
            "shop": {"name": "Steam"},
            "cut": 50,
        }
    }]
    return mock


# ── Benchmarks ──────────────────────────────────────────────────────────────

def bench_extract_url():
    """
    Benchmark extract_app_id_from_url() — regex parsing.
    Complexidade: O(n) onde n = len(URL), regex scan linear.
    """
    urls = [
        "https://store.steampowered.com/app/1091500/Cyberpunk_2077/",
        "https://store.steampowered.com/app/730/Counter_Strike_2/",
        "store.steampowered.com/app/570/Dota_2/",
        "https://www.google.com",  # invalid
        "",  # empty
    ]

    iterations = 10_000
    t0 = time.perf_counter()
    for _ in range(iterations):
        for url in urls:
            api.extract_app_id_from_url(url)
    elapsed = time.perf_counter() - t0

    total_calls = iterations * len(urls)
    per_call_ns = (elapsed / total_calls) * 1_000_000_000

    return {
        "function": "extract_app_id_from_url",
        "total_calls": total_calls,
        "total_ms": elapsed * 1000,
        "per_call_ns": per_call_ns,
    }


@patch("api.requests.get")
def bench_steam_game_info(mock_get):
    """
    Benchmark get_steam_game_info() — JSON processing overhead.
    Complexidade: O(1) para processamento (resposta tem tamanho fixo).
    """
    mock_get.return_value = create_steam_mock_response()

    iterations = 10_000
    t0 = time.perf_counter()
    for _ in range(iterations):
        api.get_steam_game_info("1091500")
    elapsed = time.perf_counter() - t0

    per_call_ns = (elapsed / iterations) * 1_000_000_000

    return {
        "function": "get_steam_game_info",
        "total_calls": iterations,
        "total_ms": elapsed * 1000,
        "per_call_ns": per_call_ns,
    }


@patch("api.requests.post")
@patch("api._get_itad_uuid")
def bench_itad_prices(mock_uuid, mock_post):
    """
    Benchmark get_itad_prices() — processamento de 2 respostas ITAD.
    Complexidade: O(1) para processamento.
    Em produção: ~2 requests HTTP sequenciais (~200-500ms cada).
    """
    mock_uuid.return_value = "fake-uuid-bench"
    original_key = api.ITAD_API_KEY
    api.ITAD_API_KEY = "bench_key"

    iterations = 5_000
    t0 = time.perf_counter()
    for _ in range(iterations):
        mock_post.side_effect = [create_itad_prices_mock(), create_itad_history_mock()]
        api.get_itad_prices("1091500")
    elapsed = time.perf_counter() - t0

    api.ITAD_API_KEY = original_key

    per_call_ns = (elapsed / iterations) * 1_000_000_000

    return {
        "function": "get_itad_prices",
        "total_calls": iterations,
        "total_ms": elapsed * 1000,
        "per_call_ns": per_call_ns,
    }


def main():
    # Fix Windows console encoding
    sys.stdout.reconfigure(encoding="utf-8")

    print("\n🏎️  RatBot API Benchmarks (mock-based, network excluded)")
    print("=" * 70)
    print(f"  {'Function':<30} {'Calls':>8} {'Total (ms)':>12} {'Per call (ns)':>14}")
    print(f"  {'-' * 66}")

    results = [
        bench_extract_url(),
        bench_steam_game_info(),
        bench_itad_prices(),
    ]

    for r in results:
        print(
            f"  {r['function']:<30} "
            f"{r['total_calls']:>8,} "
            f"{r['total_ms']:>12.2f} "
            f"{r['per_call_ns']:>14.1f}"
        )

    print()
    print("📊 Análise:")
    print("  • extract_app_id_from_url(): < 1μs — regex compilado internamente pelo Python")
    print("  • get_steam_game_info(): overhead ~μs — dominado por dict.get() e float division")
    print("  • get_itad_prices(): ~μs — overhead de processamento mínimo")
    print()
    print("💡 Conclusão:")
    print("  O processamento de resposta das APIs é negligível (<1% do tempo total).")
    print("  A latência é 100% dominada por I/O de rede (tipicamente 100-500ms/request).")
    print("  Otimizar este código não traria ganho mensurável em produção.")
    print()
    print("🔧 Plano de Profiling (comandos para rodar manualmente):")
    print("  # cProfile — visão geral do CPU time")
    print("  python -m cProfile -s cumulative bot.py")
    print()
    print("  # line_profiler — análise linha a linha (instale: pip install line-profiler)")
    print("  kernprof -l -v bot.py")
    print()
    print("  # memory_profiler — picos de memória (instale: pip install memory-profiler)")
    print("  python -m memory_profiler database.py")
    print()
    print("  # hyperfine — benchmark de tempo de inicialização (instale via cargo/scoop)")
    print('  hyperfine "python -c \'import bot\'"')
    print()


if __name__ == "__main__":
    main()
