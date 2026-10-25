#!/usr/bin/env python3
"""
model_analysis/evaluate_snapshot_scaling.py

Run evaluations with various numbers of move snapshots for each user:
- hikaru
- stuffyness
- saiteja1000
- Schwoby_1200

Strict mode:
- 100% real game move snapshots and trained model weights.
- Evaluates move prediction accuracy (Top-1 %, Top-3 %, Loss) and decision time predictions (MedAE, within ±2s/±5s, correlation r).
- Exports full results to model_analysis/snapshot_scaling_evaluation.csv.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_BACKEND_URL = "http://localhost:8000"
DEFAULT_TARGET_USERS = [
    ("hikaru", "hikaru"),
    ("stuffyness", "stuffyness"),
    ("saiteja1000", "saiteja1000"),
    ("Schwoby_1200", "schwoby_1200"),
]
DEFAULT_SNAPSHOT_COUNTS = [50, 100, 200, 350, 500, 750, 1000]


def run_snapshot_evaluation(
    api_name: str,
    snapshot_counts: list[int],
    limit_games: int = 30,
    backend_url: str = DEFAULT_BACKEND_URL,
) -> list[dict]:
    counts_str = ",".join(str(c) for c in snapshot_counts)
    url = f"{backend_url}/api/clones/{api_name}/benchmark-snapshots?counts={counts_str}&limit={limit_games}"
    req = urllib.request.Request(url, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data
    except urllib.error.URLError as e:
        raise ConnectionError(f"Backend connection failed at {url}: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate chess clone accuracy across varying numbers of snapshots.")
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL, help="Backend URL")
    parser.add_argument("--limit-games", type=int, default=30, help="Max games to sample per player")
    parser.add_argument("--counts", default="50,100,200,350,500,750,1000", help="Comma-separated snapshot sizes")
    parser.add_argument("--out-csv", default="model_analysis/snapshot_scaling_evaluation.csv", help="Output CSV path")
    args = parser.parse_args()

    snapshot_counts = [int(c.strip()) for c in args.counts.split(",") if c.strip()]
    out_csv = Path(args.out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("SNAPSHOT SCALING EVALUATION SUITE")
    print(f"Backend:  {args.backend_url}")
    print(f"Counts:   {snapshot_counts}")
    print(f"Users:    {', '.join(d for d, _ in DEFAULT_TARGET_USERS)}")
    print("=" * 80)
    print()

    all_rows = []
    results_by_user = {}

    for display_name, api_name in DEFAULT_TARGET_USERS:
        print(f"[*] Running snapshot scaling for {display_name} ({api_name})...", end="", flush=True)
        try:
            records = run_snapshot_evaluation(
                api_name=api_name,
                snapshot_counts=snapshot_counts,
                limit_games=args.limit_games,
                backend_url=args.backend_url,
            )
            # Tag with display_name
            for r in records:
                r["display_username"] = display_name
            results_by_user[display_name] = records
            all_rows.extend(records)
            print(f" OK ({len(records)} evaluation tiers)")
        except Exception as e:
            print(f" FAILED: {e}")
            sys.exit(1)

    # Save to CSV
    if all_rows:
        fieldnames = [
            "display_username",
            "player_id",
            "snapshots_evaluated",
            "total_available_positions",
            "games_analyzed",
            "maia_top1_pct",
            "clone_top1_pct",
            "top1_delta_pct",
            "maia_top3_pct",
            "clone_top3_pct",
            "top3_delta_pct",
            "maia_loss",
            "clone_loss",
            "loss_reduction",
            "valid_time_positions",
            "actual_median_sec",
            "pred_median_sec",
            "median_tempo_delta_sec",
            "medae_sec",
            "mae_sec",
            "rmse_sec",
            "within_1s_pct",
            "within_2s_pct",
            "within_5s_pct",
            "correlation_r",
        ]
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"\n[+] Saved full scaling CSV to {out_csv.resolve()}")

    # Render formatted markdown tables
    print()
    print("=" * 80)
    print("EVALUATION RESULTS ACROSS SNAPSHOT COUNTS")
    print("=" * 80)

    for display_name, records in results_by_user.items():
        print(f"\n### User: `{display_name}` (Total Game Positions: {records[0]['total_available_positions']:,})")
        print("| Snapshots | Maia Top-1 | Clone Top-1 | Δ Top-1 | Maia Top-3 | Clone Top-3 | Maia Loss | Clone Loss | Loss Δ | Pred Med (s) | Actual Med (s) | MedAE (s) | Within ±2s | Pearson r |")
        print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for r in records:
            k = r["snapshots_evaluated"]
            m1 = r["maia_top1_pct"]
            c1 = r["clone_top1_pct"]
            d1 = r["top1_delta_pct"]
            sign_d1 = f"+{d1:.2f}%" if d1 > 0 else f"{d1:.2f}%"

            m3 = r["maia_top3_pct"]
            c3 = r["clone_top3_pct"]

            ml = r["maia_loss"]
            cl = r["clone_loss"]
            ld = r["loss_reduction"]
            sign_ld = f"-{ld:.4f}" if ld > 0 else (f"+{abs(ld):.4f}" if ld < 0 else "0.0000")

            prd_m = r["pred_median_sec"]
            act_m = r["actual_median_sec"]
            medae = r["medae_sec"]
            w2 = r["within_2s_pct"]
            r_corr = r["correlation_r"]

            print(
                f"| {k:,} | {m1:.2f}% | **{c1:.2f}%** | {sign_d1} | {m3:.2f}% | **{c3:.2f}%** | "
                f"{ml:.4f} | **{cl:.4f}** | {sign_ld} | {prd_m:.2f}s | {act_m:.2f}s | {medae:.2f}s | {w2:.1f}% | {r_corr:.3f} |"
            )


if __name__ == "__main__":
    main()
