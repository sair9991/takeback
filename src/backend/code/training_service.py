"""
training_service.py - Self-contained background training runner for opponent clones.
Orchestrates downloading games, extracting board snapshots & Maia-3 logits, and training the Clone MLP.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Callable, Optional

import torch
import torch.nn as nn
import torch.nn.functional as F

import chess_pgn_parser
import helper

# Project root: 4 levels up from this file (src/backend/code/training_service.py -> ROOT)
ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = ROOT / "Model"
maia3_dir = ROOT / "maia3"

if str(maia3_dir) in sys.path:
    sys.path.remove(str(maia3_dir))
sys.path.insert(0, str(maia3_dir))

for p in (str(MODEL_DIR), str(ROOT)):
    if p not in sys.path:
        sys.path.append(p)

if "maia3" in sys.modules and not getattr(sys.modules["maia3"], "__file__", None):
    del sys.modules["maia3"]


def fetch_games_for_opponent(opp: str, out_csv: Path, limit: int = 60) -> Path:
    """
    Fetches games for the opponent using the backend chess_pgn_parser.
    Checks existing local CSV for this opponent if network fetch fails.
    Never uses another player's games (e.g. stuffyness).
    """
    opp_clean = opp.strip().lower()
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    # 1. Try Chess.com API via backend chess_pgn_parser
    try:
        print(f"[Training] Fetching games for '{opp}' from Chess.com...")
        out_csv, games = chess_pgn_parser.fetch_user_games_and_save(opp, limit=limit, out_csv=out_csv)
        if out_csv.is_file() and out_csv.stat().st_size > 0:
            print(f"[Training] Downloaded {len(games)} games from Chess.com for '{opp}'.")
            return out_csv
    except Exception as e:
        print(f"[Training] Chess.com API fetch failed for '{opp}': {e}")

    # 2. Check if local CSV already exists strictly for this opponent
    for candidate in [
        ROOT / f"{opp_clean}.csv",
        ROOT / "data" / f"{opp_clean}.csv",
    ]:
        if candidate.is_file() and candidate.resolve() != out_csv.resolve():
            print(f"[Training] Using existing local archive: {candidate.name}")
            shutil.copy(candidate, out_csv)
            return out_csv

    if out_csv.is_file() and out_csv.stat().st_size > 0:
        return out_csv

    raise RuntimeError(f"Could not fetch or locate games for opponent '{opp}'.")


def train_clone_mlp(dataset_file: str | Path, out_weights: str | Path) -> Path:
    """
    Trains the personalized Clone MLP on pre-extracted Maia-3 logits and context features.
    """
    from Model.implementation import Clone, compute_loss, move_accuracy

    dataset_path = Path(dataset_file)
    out_path = Path(out_weights)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not dataset_path.is_file():
        raise FileNotFoundError(f"Dataset not found at {dataset_path}")

    tensors = torch.load(dataset_path, map_location="cpu", weights_only=False)
    game_ids = tensors.get("game_ids", [])
    if not game_ids or len(tensors["X"]) == 0:
        raise ValueError("Dataset contains no snapshot tensors to train on.")

    # Split 80/20 by unique games to prevent leakage
    unique_games = list(dict.fromkeys(game_ids))
    n_train_games = max(1, int(len(unique_games) * 0.8))
    train_set = set(unique_games[:n_train_games])

    train_idx = torch.tensor([i for i, gid in enumerate(game_ids) if gid in train_set], dtype=torch.long)
    val_idx = torch.tensor([i for i, gid in enumerate(game_ids) if gid not in train_set], dtype=torch.long)
    if len(val_idx) == 0:
        val_idx = train_idx

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

    device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
    model = Clone().to(device)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    batch_size = 128
    N = len(train[0])

    train_dev = tuple(t.to(device) for t in train)
    val_dev = tuple(t.to(device) for t in val)

    best_val, best_state, patience, bad = float("inf"), None, 5, 0

    for epoch in range(40):
        model.train()
        perm = torch.randperm(N, device=device)
        for i in range(0, N, batch_size):
            idx = perm[i : i + batch_size]
            batch = [t[idx] for t in train_dev]
            loss, _, _ = compute_loss(model, *batch)
            opt.zero_grad()
            loss.backward()
            opt.step()

        model.eval()
        with torch.no_grad():
            _, v_move, _ = compute_loss(model, *val_dev)

        if v_move < best_val:
            best_val = v_move.item()
            bad = 0
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= patience:
                break

    if best_state is None:
        best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

    torch.save(best_state, out_path)
    print(f"[Training] Saved clone weights to {out_path}")
    return out_path


def run_training_pipeline(opp: str, broadcast_cb: Optional[Callable[[str, int, str], None]] = None) -> Path:
    """
    Full real training pipeline:
    1. Fetch games via backend chess_pgn_parser.py
    2. Extract snapshots via Model.snapshots
    3. Extract Maia-3 logits via Model.maia_extractor
    4. Train Clone MLP
    5. Save checkpoint to models/{opp}.pt and register in SQLite models table.
    """
    def notify(status: str, progress: int, msg: str):
        print(f"[Training: {opp}] {progress}% - {msg}")
        if broadcast_cb:
            try:
                broadcast_cb(status, progress, msg)
            except Exception:
                pass

    opp_clean = opp.strip().lower()
    data_dir = ROOT / "data"
    models_dir = ROOT / "models"
    data_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)

    csv_path = data_dir / f"{opp_clean}.csv"
    snapshots_csv = data_dir / f"{opp_clean}_snapshots.csv"
    logits_csv = data_dir / f"{opp_clean}_logits.csv"
    dataset_pt = data_dir / f"{opp_clean}_dataset.pt"
    final_weights = models_dir / f"{opp_clean}.pt"

    # Step 1: Fetch data (25%)
    notify("fetching_data", 25, f"Fetching games from Chess.com for {opp}...")
    fetch_games_for_opponent(opp, csv_path, limit=60)

    # Step 2: Make snapshots (50%)
    notify("snapshots", 50, "Extracting move snapshots and clock labels...")
    from Model.snapshots import load_rows, build_snapshot_table, write_csv
    rows = load_rows(str(csv_path))
    snaps, report = build_snapshot_table(rows, player_id=opp_clean)
    if not snaps:
        raise ValueError(f"No valid snapshots extracted for {opp_clean}. Report: {report}")
    write_csv(snaps, str(snapshots_csv))

    # Step 3: Extract Maia-3 logits (75%)
    notify("maia_features", 75, "Extracting Maia-3 move features...")
    from Model.maia_extractor import extract_snapshots_and_maia_logits
    import pandas as pd
    df_table, tensors = extract_snapshots_and_maia_logits(
        csv_path=str(csv_path),
        limit_games=60,
        batch_size=64,
    )
    df_table.to_csv(logits_csv, index=False)
    torch.save(tensors, dataset_pt)

    # Step 4: Train Clone MLP (90%)
    notify("training", 90, "Training personalized clone neural network...")
    train_clone_mlp(dataset_pt, final_weights)

    # Step 5: Save in SQLite models table
    helper.execute(
        """
        INSERT INTO models (player_id, weights_path)
        VALUES (?, ?)
        ON CONFLICT(player_id) DO UPDATE SET weights_path = excluded.weights_path
        """,
        (opp_clean, f"models/{opp_clean}.pt"),
    )

    notify("completed", 100, f"Model for {opp} trained and cached!")
    return final_weights
