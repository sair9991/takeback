"""
src/backend/model_service.py - Backend service interface for the Chess Player Clone.

Three Core Pipeline Functions:
  1. populate_user_data: Takes in a username and populates their data into the database
     (users, games, and moves tables) without creating any CSV file.
  2. train_model_from_db: Reads the database for the game data and trains the clone model,
     saving the model weights back to the database (models table).
  3. evaluate_model_and_save_stats: Tests and evaluates the model against Maia-3 baseline,
     saving its testing statistics into the new eval_stats field in the models table.
"""

from __future__ import annotations

import io
import json
import os
import sys
from collections import deque
from pathlib import Path
from typing import Any, Optional

import chess
import chess.pgn
import torch
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parent.parent.parent
FINAL_MODEL_DIR = ROOT / "FINAL_MODEL"
MODEL_DIR = ROOT / "Model"

for p in (str(ROOT / "maia3"), str(ROOT), str(FINAL_MODEL_DIR), str(MODEL_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from src.backend.database import Database, parse_clock_string
from FINAL_MODEL.chess_pgn_parser import fetch_user_games
from FINAL_MODEL.implementation import Clone, compute_loss, move_accuracy
from FINAL_MODEL.maia_extractor import extract_snapshots_and_maia_logits
from Model.service import evaluate_clone, predict_move


# --------------------------------------------------------------------------- #
# Function 1: Populate user data without creating any CSV file
# --------------------------------------------------------------------------- #
def populate_user_data(
    username: str,
    limit: int = 500,
    db: Optional[Database] = None,
) -> dict[str, Any]:
    """
    Takes in a user's username and populates their data into the SQLite database.
    DOES NOT create any CSV file.

    Populates:
      - users: user_id and chess_com_username
      - games: match metadata, colors, elos, results
      - moves: individual move sequence with clocks and time remaining
    """
    db = db or Database()
    user_id = username.strip().lower()

    # 1. Register or update user record
    db.create_or_get_user(user_id=user_id, chess_com_username=username.strip())

    # 2. Fetch games from Chess.com directly into memory
    print(f"Fetching games for user '{username}' from Chess.com...")
    games = fetch_user_games(username=username, limit=limit)
    print(f"Fetched {len(games)} games in-memory. Populating database...")

    # 3. Insert games and individual moves into SQLite
    stats = db.import_games_list(games=games, default_player_id=user_id, src="chess.com")
    print(f"Populated database for '{user_id}': {stats['games_imported']} games, {stats['moves_imported']} moves.")

    return {
        "user_id": user_id,
        "chess_com_username": username.strip(),
        "games_imported": stats["games_imported"],
        "moves_imported": stats["moves_imported"],
    }


# --------------------------------------------------------------------------- #
# Function 2: Read game data from database, train model, save weights to DB
# --------------------------------------------------------------------------- #
def train_model_from_db(
    username: str,
    db: Optional[Database] = None,
    checkpoint_path: str = "./models/maia3-5m.pt",
    batch_size: int = 128,
    epochs: int = 100,
    patience: int = 5,
    out_dir: Optional[str | Path] = None,
    force_recompute_features: bool = False,
) -> dict[str, Any]:
    """
    Reads the database for the user's game and move data and trains the Clone model,
    saving the model weights back to the database models table.
    """
    db = db or Database()
    player_id = username.strip().lower()

    out_dir = Path(out_dir) if out_dir else ROOT / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    weights_path = out_dir / f"{player_id}_clone.pt"
    dataset_path = out_dir / f"{player_id}_snapshots_dataset.pt"

    # Check for existing precomputed tensor dataset or compute from DB records
    if not force_recompute_features and dataset_path.is_file():
        print(f"Loading existing cached tensors from {dataset_path}...")
        tensors = torch.load(dataset_path, map_location="cpu", weights_only=False)
    else:
        # 1. Read games and moves directly from database
        print(f"Reading games and moves from database for user '{player_id}'...")
        games = db.get_games_by_player_id(player_id)
        if not games:
            raise ValueError(f"No games found in database for user '{player_id}'. Run populate_user_data first.")

        # Reconstruct in-memory game rows
        rows = []
        for g in games:
            ext_game_id = g.get("game_id") or str(g["id"])
            move_rows = db.get_moves_by_game_id(ext_game_id)

            movetext_parts = []
            for m in move_rows:
                ply = m["ply"]
                san = m["move"]
                clk = m.get("clock_str") or (f"{m['time_remaining']:.1f}" if m.get("time_remaining") is not None else "")
                clk_annotation = f" {{[%clk {clk}]}}" if clk else ""
                if ply % 2 == 1:
                    movenum = (ply + 1) // 2
                    movetext_parts.append(f"{movenum}. {san}{clk_annotation}")
                else:
                    movetext_parts.append(f"{san}{clk_annotation}")

            rows.append({
                "player_id": g["player_id"],
                "date": g["date"] or "",
                "player_color": g["player_color"].capitalize(),
                "time_control": g["time_control"] or "600",
                "player_elo": g["player_elo"] or 1500,
                "opponent": g["opponent_username"] or "",
                "opponent_elo": g["opponent_elo"] or 1500,
                "result": g["result"] or "",
                "moves": " ".join(movetext_parts),
            })

        print(f"Reconstructed {len(rows)} game records from DB. Running Maia-3 feature extraction...")
        # 2. Extract Maia-3 logits and 28-feature tensors directly from rows in-memory
        _, tensors = extract_snapshots_and_maia_logits(
            rows=rows,
            checkpoint_path=checkpoint_path,
            batch_size=batch_size,
            player_id=player_id,
        )
        torch.save(tensors, dataset_path)
        print(f"Saved extracted tensors to {dataset_path.name}")

    # 3. Train Clone MLP model
    print(f"Training Clone model on {len(tensors['target_idx'])} snapshots...")
    game_ids = tensors["game_ids"]
    unique_games = list(dict.fromkeys(game_ids))
    n_train = int(len(unique_games) * 0.8)
    train_games = set(unique_games[:n_train])

    train_idx = torch.tensor([i for i, gid in enumerate(game_ids) if gid in train_games], dtype=torch.long)
    val_idx = torch.tensor([i for i, gid in enumerate(game_ids) if gid not in train_games], dtype=torch.long)

    train_data = (
        tensors["X"][train_idx],
        tensors["maia_logits"][train_idx],
        tensors["mask"][train_idx],
        tensors["target_idx"][train_idx],
        tensors["seconds"][train_idx],
    )
    val_data = (
        tensors["X"][val_idx],
        tensors["maia_logits"][val_idx],
        tensors["mask"][val_idx],
        tensors["target_idx"][val_idx],
        tensors["seconds"][val_idx],
    )

    model = Clone()
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    best_val_move = float("inf")
    best_state = None
    bad_epochs = 0
    batch_train_size = 256
    n_samples = len(train_data[0])

    for epoch in range(epochs):
        model.train()
        perm = torch.randperm(n_samples)
        for i in range(0, n_samples, batch_train_size):
            b_idx = perm[i : i + batch_train_size]
            batch = [t[b_idx] for t in train_data]
            loss, _, _ = compute_loss(model, *batch)
            opt.zero_grad()
            loss.backward()
            opt.step()

        model.eval()
        with torch.no_grad():
            _, val_move, val_time = compute_loss(model, *val_data)
        val_acc = move_accuracy(model, *val_data[:4])

        if val_move.item() < best_val_move:
            best_val_move = val_move.item()
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            bad_epochs = 0
        else:
            bad_epochs += 1
            if bad_epochs >= patience:
                break

    if best_state is not None:
        model.load_state_dict(best_state)

    final_acc = move_accuracy(model, *val_data[:4])
    torch.save(model.state_dict(), weights_path)
    print(f"Training finished: best val move loss = {best_val_move:.4f}, acc = {final_acc:.3f}")

    # 4. Save model weights back to database models table
    db_record = db.save_model_weights(
        player_id=player_id,
        weights_path=weights_path,
        val_accuracy=final_acc,
        val_loss=best_val_move,
    )
    print(f"Saved model weights to database models table for user '{player_id}'.")

    return {
        "player_id": player_id,
        "weights_path": str(weights_path),
        "val_accuracy": final_acc,
        "val_loss": best_val_move,
        "dataset_path": str(dataset_path),
        "db_record": db_record,
    }


# --------------------------------------------------------------------------- #
# Function 3: Test and evaluate model, saving statistics into models table
# --------------------------------------------------------------------------- #
def evaluate_model_and_save_stats(
    username: str,
    db: Optional[Database] = None,
    split: str = "val",
    dataset_path: Optional[str | Path] = None,
) -> dict[str, Any]:
    """
    Tests and evaluates the model, saving its statistics into the new eval_stats
    field in the database (the models table).
    """
    db = db or Database()
    player_id = username.strip().lower()

    # 1. Fetch trained model weights record from DB
    model_row = db.get_model_weights(player_id)
    if not model_row or not model_row.get("weights_path"):
        raise ValueError(f"No trained model found for user '{player_id}' in models table.")

    weights_path = Path(model_row["weights_path"])
    if not weights_path.is_file():
        raise FileNotFoundError(f"Model checkpoint file not found at: {weights_path}")

    # 2. Locate tensors dataset
    if dataset_path is None:
        dataset_path = next(
            (p for p in [
                ROOT / "data" / f"{player_id}_snapshots_dataset.pt",
                ROOT / "snapshots_dataset.pt",
            ] if p.is_file()),
            None,
        )
    if not dataset_path or not Path(dataset_path).is_file():
        raise FileNotFoundError(f"No snapshot tensors dataset found for '{player_id}'.")

    tensors = torch.load(dataset_path, map_location="cpu", weights_only=False)

    # 3. Evaluate Clone vs Maia-3 Baseline
    stats = evaluate_clone(str(weights_path), tensors=tensors, split=split)
    stats["split"] = split
    stats["total_snapshots"] = len(tensors["target_idx"])
    stats["val_accuracy"] = model_row.get("val_accuracy")
    stats["val_loss"] = model_row.get("val_loss")

    # 4. Save statistics into eval_stats field in the models table
    db.save_model_stats(player_id=player_id, eval_stats=stats)
    print(f"Saved evaluation statistics for user '{player_id}' into models.eval_stats.")

    return stats


__all__ = [
    "Database",
    "parse_clock_string",
    "populate_user_data",
    "train_model_from_db",
    "evaluate_model_and_save_stats",
    "predict_move",
    "evaluate_clone",
]
