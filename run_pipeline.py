"""
run_pipeline.py - Complete End-to-End Pipeline Runner:
From raw games CSV -> snapshots -> Maia-3 logits extraction -> table & tensors -> training & evaluation.

Usage:
  python run_pipeline.py [--csv stuffyness.csv] [--limit-games 500] [--epochs 35]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import torch

from pipeline.maia_extractor import extract_snapshots_and_maia_logits
from pipeline.train import run_training_pipeline


def main():
    parser = argparse.ArgumentParser(description="End-to-End Maia-3 Chess Clone Pipeline")
    parser.add_argument("--csv", default="stuffyness.csv", help="Input games CSV")
    parser.add_argument("--out-csv", default="snapshots_with_logits.csv", help="Output CSV table with logits")
    parser.add_argument("--out-pt", default="snapshots_dataset.pt", help="Output PyTorch tensors file")
    parser.add_argument("--model-checkpoint", default="./models/maia3-5m.pt", help="Path to Maia-3 checkpoint")
    parser.add_argument("--model-name", default="maia3-5m", help="Maia-3 model variant")
    parser.add_argument("--limit-games", type=int, default=None, help="Limit number of games (for fast tests)")
    parser.add_argument("--batch-size", type=int, default=128, help="Batch size for Maia-3 inference")
    parser.add_argument("--train-batch-size", type=int, default=256, help="Batch size for model training")
    parser.add_argument("--epochs", type=int, default=30, help="Training epochs for MLP adapter")
    parser.add_argument("--skip-extraction", action="store_true", help="Skip extraction if dataset already exists")
    args = parser.parse_args()

    print("=" * 70)
    print("CHESS PLAYER CLONE: MAIA-3 END-TO-END PIPELINE")
    print("=" * 70)

    # Step 1: Run Maia-3 extraction if needed
    if args.skip_extraction and os.path.exists(args.out_pt) and os.path.exists(args.out_csv):
        print(f"Skipping extraction, using existing {args.out_pt} and {args.out_csv}")
    else:
        print(f"\n[Step 1] Extracting snapshots and computing Maia-3 logits from {args.csv}...")
        df_table, tensors = extract_snapshots_and_maia_logits(
            csv_path=args.csv,
            checkpoint_path=args.model_checkpoint,
            model_name=args.model_name,
            batch_size=args.batch_size,
            limit_games=args.limit_games,
        )

        print(f"\n[Step 2] Saving snapshot logits table to {args.out_csv}...")
        df_table.to_csv(args.out_csv, index=False)

        print(f"Saving training tensors to {args.out_pt}...")
        torch.save(tensors, args.out_pt)
        print(f"Successfully created table with {len(df_table)} rows.")

    # Step 2: Train and evaluate baselines and MLP adapter
    print("\n[Step 3] Training and evaluating models on real Maia-3 outputs...")
    results = run_training_pipeline(
        dataset_pt_path=args.out_pt,
        batch_size=args.train_batch_size,
        epochs=args.epochs,
    )

    # Step 3: Print final evaluation comparison table
    print("\n" + "=" * 70)
    print("FINAL EVALUATION RESULTS SUMMARY")
    print("=" * 70)
    print(f"{'Model':<24} | {'Move NLL':<10} | {'Top-1 Acc':<10} | {'Top-3 Acc':<10} | {'Time NLL':<10}")
    print("-" * 70)

    maia = results["plain_maia"]
    linear = results["linear_adapter"]
    mlp = results["mlp_adapter"]

    print(f"{'Plain Maia-3 (Baseline)':<24} | {maia['move_nll']:<10.4f} | {maia['top1_acc']*100:<9.2f}% | {maia['top3_acc']*100:<9.2f}% | {maia['time_nll']:<10.4f}")
    print(f"{'Linear Adapter':<24} | {linear['move_nll']:<10.4f} | {linear['top1_acc']*100:<9.2f}% | {linear['top3_acc']*100:<9.2f}% | {linear['time_nll']:<10.4f}")
    print(f"{'MLP Adapter (Ours)':<24} | {mlp['move_nll']:<10.4f} | {mlp['top1_acc']*100:<9.2f}% | {mlp['top3_acc']*100:<9.2f}% | {mlp['time_nll']:<10.4f}")
    print("-" * 70)

    rel_gain = results["mlp_rel_move_gain_pct"]
    time_gain = results["mlp_rel_time_gain_pct"]
    print(f"Relative Move NLL Improvement over Maia-3: {rel_gain:+.2f}%")
    print(f"Relative Think-Time NLL Improvement over Constant: {time_gain:+.2f}%")

    if rel_gain >= 1.0:
        print("\n>>> DECISION GATE C: PASSED! (>= 1.0% relative improvement over Maia-3)")
    else:
        print(f"\n>>> DECISION GATE C: Move improvement {rel_gain:.2f}% (Target: >= 1.0%)")

    print("=" * 70)


if __name__ == "__main__":
    main()

