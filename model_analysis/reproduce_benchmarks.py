#!/usr/bin/env python3
"""
model_analysis/reproduce_benchmarks.py

Reproduce comparative benchmark evaluations:
1. Move Prediction: Maia-3 Baseline vs. Fine-Tuned Clone Model (Top-1, Top-3, Loss)
2. Decision Time Prediction: Log-normal Head vs. Actual Game Clocks

Strict Requirements:
- No fallbacks, zero synthetic/dummy data.
- Only real information evaluated from actual games and trained model checkpoints.
- Fails with clean ConnectionError / RuntimeError if backend or database is unreachable.

Usage:
    python3 reproduce_benchmarks.py
    python3 reproduce_benchmarks.py --players hikaru,aemara84,stuffyness,rguruna,ch_uz --limit 50
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Add project directories to sys.path so analysis_pkg is importable
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:
    from analysis_pkg import (
        DEFAULT_BACKEND_URL,
        batch_benchmark,
        benchmark_model,
        format_benchmark_tables,
    )
except ImportError:
    # Direct import fallback if executed from within package
    from analysis_pkg.model_analysis import (
        DEFAULT_BACKEND_URL,
        batch_benchmark,
        benchmark_model,
        format_benchmark_tables,
    )


DEFAULT_TARGET_PLAYERS = [
    "hikaru",
    "aemara84",
    "stuffyness",
    "rguruna",
    "ch_uz",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reproduce Maia-3 vs Clone move accuracy & decision tempo benchmarks."
    )
    parser.add_argument(
        "--players",
        type=str,
        default=",".join(DEFAULT_TARGET_PLAYERS),
        help="Comma-separated player usernames (default: hikaru,aemara84,stuffyness,rguruna,ch_uz)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum games to analyze per player (default: 50)",
    )
    parser.add_argument(
        "--backend-url",
        type=str,
        default=DEFAULT_BACKEND_URL,
        help=f"Backend API URL (default: {DEFAULT_BACKEND_URL})",
    )
    parser.add_argument(
        "--save-json",
        type=str,
        default=None,
        help="Optional path to save raw benchmark results as JSON",
    )
    parser.add_argument(
        "--save-csv",
        type=str,
        default=None,
        help="Optional path to save benchmark results as CSV",
    )

    args = parser.parse_args()
    target_players = [p.strip().lower() for p in args.players.split(",") if p.strip()]

    print("=" * 80)
    print("CHESS CLONE BENCHMARK REPRODUCTION SUITE")
    print(f"Backend Target: {args.backend_url}")
    print(f"Game Limit:     {args.limit} games per player")
    print(f"Players:        {', '.join(target_players)}")
    print("Mode:           Strict (Zero Mock Data, Real Model Inference Only)")
    print("=" * 80)
    print()

    results = []
    for player in target_players:
        print(f"[*] Evaluating player '{player}'...", end="", flush=True)
        try:
            res = benchmark_model(
                person=player,
                limit_games=args.limit,
                backend_url=args.backend_url,
            )
            results.append(res)
            pos = res.get("positions_evaluated", 0)
            games = res.get("games_analyzed", 0)
            print(f" OK ({games} games, {pos} positions)")
        except ConnectionError as e:
            print(f" FAILED (Connection Error)")
            print(f"\n[ERROR] Backend connection failed: {e}", file=sys.stderr)
            print("Ensure Docker container 'chess_backend' is running on port 8000.", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f" FAILED")
            print(f"\n[ERROR] Failed to benchmark player '{player}': {e}", file=sys.stderr)
            sys.exit(1)

    print()
    print("=" * 80)
    print("BENCHMARK RESULTS")
    print("=" * 80)
    print()

    # Render formatted markdown tables
    tables_md = format_benchmark_tables(results)
    print(tables_md)

    if args.save_json:
        out_path = Path(args.save_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print()
        print(f"Raw benchmark metrics saved to {out_path.resolve()}")

    if args.save_csv:
        import csv
        csv_path = Path(args.save_csv)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_rows = []
        for r in results:
            mv = r.get("move_evaluation", {})
            tm = r.get("time_evaluation", {})
            csv_rows.append({
                "username": r.get("player_id"),
                "games_analyzed": r.get("games_analyzed", 0),
                "positions_evaluated": r.get("positions_evaluated", 0),
                "maia_top1_pct": mv.get("maia_top1_pct", 0.0),
                "clone_top1_pct": mv.get("clone_top1_pct", 0.0),
                "top1_delta_pct": mv.get("top1_delta_pct", 0.0),
                "maia_top3_pct": mv.get("maia_top3_pct", 0.0),
                "clone_top3_pct": mv.get("clone_top3_pct", 0.0),
                "top3_delta_pct": mv.get("top3_delta_pct", 0.0),
                "maia_loss": mv.get("maia_loss", 0.0),
                "clone_loss": mv.get("clone_loss", 0.0),
                "loss_reduction": mv.get("loss_reduction", 0.0),
                "valid_time_positions": tm.get("valid_positions", 0),
                "actual_median_time_s": tm.get("actual_median_sec", 0.0),
                "pred_median_time_s": tm.get("pred_median_sec", 0.0),
                "median_tempo_delta_s": tm.get("median_tempo_delta_sec", 0.0),
                "actual_mean_time_s": tm.get("actual_mean_sec", 0.0),
                "pred_mean_time_s": tm.get("pred_mean_sec", 0.0),
                "medae_s": tm.get("medae_sec", 0.0),
                "mae_s": tm.get("mae_sec", 0.0),
                "rmse_s": tm.get("rmse_sec", 0.0),
                "within_1s_pct": tm.get("within_1s_pct", 0.0),
                "within_2s_pct": tm.get("within_2s_pct", 0.0),
                "within_5s_pct": tm.get("within_5s_pct", 0.0),
                "time_correlation_r": tm.get("correlation_r", 0.0),
            })
        if csv_rows:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()))
                writer.writeheader()
                writer.writerows(csv_rows)
            print()
            print(f"Benchmark CSV saved to {csv_path.resolve()}")


if __name__ == "__main__":
    main()
