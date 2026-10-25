"""
train_and_play.py - Complete End-to-End Chess Player Clone Pipeline.

Takes in a raw games CSV file, performs data cleaning, extracts Maia-3 logits
and 28-feature vectors, trains the Clone model, and produces a playable
clone checkpoint for Model/play_clone.py.

Usage:
    # 1. Train from CSV and save model:
    python train_and_play.py stuffyness.csv

    # 2. Train and immediately play against the clone:
    python train_and_play.py stuffyness.csv --play

    # 3. Fast test on first 10 games:
    python train_and_play.py stuffyness.csv --limit-games 10 --play
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Setup search path so Model modules are directly importable
ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / "Model"
for p in (str(ROOT / "maia3"), str(ROOT), str(MODEL_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import torch
from Model.maia_extractor import extract_snapshots_and_maia_logits
from Model.implementation import Clone, compute_loss, move_accuracy


def split_data_by_game(tensors: dict, train_ratio: float = 0.8):
    """Splits snapshots chronologically by game_id to prevent data leakage."""
    game_ids = tensors["game_ids"]
    unique_games = list(dict.fromkeys(game_ids))
    n_train_games = int(len(unique_games) * train_ratio)
    train_set = set(unique_games[:n_train_games])

    train_idx = torch.tensor([i for i, gid in enumerate(game_ids) if gid in train_set], dtype=torch.long)
    val_idx = torch.tensor([i for i, gid in enumerate(game_ids) if gid not in train_set], dtype=torch.long)

    train = (
        tensors["X"][train_idx],
        tensors["maia_logits"][train_idx],
        tensors["mask"][train_idx],
        tensors["target_idx"][train_idx],
        tensors["seconds"][train_idx],
    )
    val = (
        tensors["X"][val_idx],
        tensors["maia_logits"][val_idx],
        tensors["mask"][val_idx],
        tensors["target_idx"][val_idx],
        tensors["seconds"][val_idx],
    )
    return train, val, len(unique_games[:n_train_games]), len(unique_games[n_train_games:])


def train_clone_model(
    train_data: tuple,
    val_data: tuple,
    epochs: int = 100,
    batch_size: int = 256,
    lr: float = 1e-3,
    weight_decay: float = 1e-4,
    patience: int = 5,
    out_path: Path = MODEL_DIR / "clone.pt",
) -> tuple[Clone, dict]:
    """Trains the Clone model on extracted snapshot tensors using early stopping."""
    model = Clone()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)

    N = len(train_data[0])
    best_val_move = float("inf")
    best_state = None
    patience_counter = 0

    print(f"\nTraining Clone model for up to {epochs} epochs (Batch size: {batch_size}, Early stopping: {patience})...")

    for epoch in range(1, epochs + 1):
        model.train()
        perm = torch.randperm(N)
        for i in range(0, N, batch_size):
            idx = perm[i : i + batch_size]
            batch = [t[idx] for t in train_data]
            loss, _, _ = compute_loss(model, *batch)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

        # Validation
        model.eval()
        with torch.no_grad():
            _, val_move, val_time = compute_loss(model, *val_data)
        val_acc = move_accuracy(model, *val_data[:4])

        improved = ""
        if val_move.item() < best_val_move:
            best_val_move = val_move.item()
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            patience_counter = 0
            improved = " *"
        else:
            patience_counter += 1

        if epoch % 5 == 0 or epoch == 1 or improved:
            print(
                f"Epoch {epoch:02d} | Val Move Loss: {val_move.item():.4f} | "
                f"Val Time Loss: {val_time.item():.4f} | Val Move Acc: {val_acc * 100:.2f}%{improved}"
            )

        if patience_counter >= patience:
            print(f"Early stopping triggered at epoch {epoch} (no validation improvement for {patience} epochs).")
            break

    # Restore best checkpoint
    if best_state is not None:
        model.load_state_dict(best_state)
    final_acc = move_accuracy(model, *val_data[:4])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out_path)
    print(f"\nBest validation move accuracy: {final_acc * 100:.2f}%")
    print(f"Saved trained clone weights to {out_path}")

    stats = {
        "best_val_move_loss": best_val_move,
        "final_accuracy": final_acc,
        "checkpoint": str(out_path),
    }
    return model, stats


def run_pipeline(
    csv_path: str,
    limit_games: int | None = None,
    batch_size: int = 128,
    train_batch_size: int = 256,
    epochs: int = 50,
    checkpoint_path: str = "./models/maia3-5m.pt",
    model_name: str = "maia3-5m",
    out_dataset_pt: str = "snapshots_dataset.pt",
    out_table_csv: str = "snapshots_with_logits.csv",
    out_model_pt: Path = MODEL_DIR / "clone.pt",
    skip_extraction: bool = False,
    play: bool = False,
):
    print("=" * 70)
    print("END-TO-END CHESS PLAYER CLONE PIPELINE")
    print("=" * 70)

    # 1. Data cleaning & Maia-3 feature extraction
    if skip_extraction and Path(out_dataset_pt).is_file():
        print(f"Using existing cached tensors from {out_dataset_pt}...")
        tensors = torch.load(out_dataset_pt, map_location="cpu", weights_only=False)
    else:
        print(f"\n[Step 1/3] Extracting snapshots and Maia-3 logits from {csv_path}...")
        df_table, tensors = extract_snapshots_and_maia_logits(
            csv_path=csv_path,
            checkpoint_path=checkpoint_path,
            model_name=model_name,
            batch_size=batch_size,
            limit_games=limit_games,
        )
        print(f"Saving snapshot table to {out_table_csv}...")
        df_table.to_csv(out_table_csv, index=False)
        print(f"Saving dataset tensors to {out_dataset_pt}...")
        torch.save(tensors, out_dataset_pt)
        print(f"Successfully processed {len(tensors['game_ids'])} snapshots.")

    # 2. Train the model
    print("\n[Step 2/3] Splitting dataset and training Clone model...")
    train_data, val_data, n_train_games, n_val_games = split_data_by_game(tensors, train_ratio=0.8)
    print(f"Game-level split: {n_train_games} train games ({len(train_data[0])} moves), "
          f"{n_val_games} val games ({len(val_data[0])} moves).")

    model, stats = train_clone_model(
        train_data=train_data,
        val_data=val_data,
        epochs=epochs,
        batch_size=train_batch_size,
        out_path=out_model_pt,
    )

    print("\n[Step 3/3] Clone model training complete and ready to play!")
    print("=" * 70)

    # 3. Interactive play
    if play:
        print("\nStarting interactive game against your clone...")
        play_script = MODEL_DIR / "play_clone.py"
        subprocess.run([sys.executable, str(play_script)], check=True)
    else:
        print("\nTo play against your clone anytime, run:")
        print("    python Model/play_clone.py")
        print("or run with '--play':")
        print(f"    python train_and_play.py {csv_path} --play")


def main():
    parser = argparse.ArgumentParser(
        description="End-to-end pipeline: CSV -> Snapshots -> Maia-3 Logits -> Train Clone -> Play"
    )
    parser.add_argument("csv_pos", nargs="?", default=None, help="Path to input games CSV (positional)")
    parser.add_argument("--csv", default=None, help="Path to input games CSV (flag)")
    parser.add_argument("--epochs", type=int, default=50, help="Max training epochs (default: 50)")
    parser.add_argument("--batch-size", type=int, default=128, help="Batch size for Maia-3 extraction")
    parser.add_argument("--train-batch-size", type=int, default=256, help="Batch size for model training")
    parser.add_argument("--limit-games", type=int, default=None, help="Limit number of games for fast runs")
    parser.add_argument("--skip-extraction", action="store_true", help="Skip extraction if dataset already exists")
    parser.add_argument("--play", action="store_true", help="Start playing against the clone right after training")
    parser.add_argument("--checkpoint-path", default="./models/maia3-5m.pt", help="Path to Maia-3 weights")
    args = parser.parse_args()

    csv_file = args.csv or args.csv_pos or "stuffyness.csv"
    if not Path(csv_file).is_file():
        # Check in model_dev/ as fallback
        alt_path = Path("model_dev") / csv_file
        if alt_path.is_file():
            csv_file = str(alt_path)
        else:
            sys.exit(f"Error: CSV file not found: {csv_file}")

    run_pipeline(
        csv_path=csv_file,
        limit_games=args.limit_games,
        batch_size=args.batch_size,
        train_batch_size=args.train_batch_size,
        epochs=args.epochs,
        checkpoint_path=args.checkpoint_path,
        skip_extraction=args.skip_extraction,
        play=args.play,
    )


if __name__ == "__main__":
    main()

