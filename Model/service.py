"""
Model/service.py - Backend-integratable service functions for the Chess Player Clone pipeline.

Provides clean, modular functions for backend API endpoints:
  - create_snapshots: CSV/games -> per-move snapshot table
  - extract_maia_logits: Snapshots -> Maia-3 move logits & 28-feature tensors
  - train_clone: Tensors -> Trained Clone model with early stopping
  - evaluate_clone: Evaluates Clone vs. Plain Maia-3 baseline metrics
  - predict_move: Live position -> Chosen move, candidate probabilities, think time
  - train_from_csv: Complete end-to-end pipeline in one function call
"""

from __future__ import annotations

import math
import os
import random
import sys
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import chess
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parent.parent
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

from Model.snapshots import (
    CLK_RE,
    DropGame,
    Snapshot,
    build_snapshot_table,
    load_rows,
    parse_clock,
    parse_time_control,
    write_csv,
    _to_int,
    make_game_id,
)
from Model.features import compute_context_features, compute_move_features
from Model.implementation import Clone, compute_loss, move_accuracy
from Model.maia_extractor import extract_snapshots_and_maia_logits, load_maia3_model


# --------------------------------------------------------------------------- #
# 1. Snapshot Creation
# --------------------------------------------------------------------------- #
def create_snapshots(
    csv_path: str,
    player_id: Optional[str] = None,
    out_csv: Optional[str] = None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """
    Parses a Chess.com games CSV into clean, per-move snapshots.
    
    Args:
        csv_path: Path to raw games CSV.
        player_id: Optional target player username to filter by.
        out_csv: Optional path to save snapshots CSV.
        
    Returns:
        (df_snapshots, drop_report_counts)
    """
    rows = load_rows(csv_path)
    snapshots, report = build_snapshot_table(rows, player_id=player_id)
    
    records = [s.__dict__ for s in snapshots]
    df = pd.DataFrame(records)
    
    if out_csv:
        Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
        write_csv(snapshots, out_csv)
        
    return df, dict(report)


# --------------------------------------------------------------------------- #
# 2. Maia-3 Logits & Feature Extraction
# --------------------------------------------------------------------------- #
def extract_maia_logits(
    csv_path: str,
    checkpoint_path: str = "./models/maia3-5m.pt",
    model_name: str = "maia3-5m",
    batch_size: int = 128,
    limit_games: Optional[int] = None,
    player_id: Optional[str] = None,
    out_table_csv: Optional[str] = None,
    out_dataset_pt: Optional[str] = None,
) -> tuple[pd.DataFrame, dict[str, torch.Tensor]]:
    """
    Runs Maia-3 on snapshots, extracting legal move logits and 28-feature tensors.
    
    Returns:
        (df_table, tensors_dict) where tensors_dict contains:
          - X: (N, 64, 28)
          - maia_logits: (N, 64)
          - mask: (N, 64)
          - target_idx: (N,)
          - seconds: (N,)
          - time_label_valid: (N,)
          - game_ids: list[str]
    """
    df_table, tensors = extract_snapshots_and_maia_logits(
        csv_path=csv_path,
        checkpoint_path=checkpoint_path,
        model_name=model_name,
        batch_size=batch_size,
        limit_games=limit_games,
        player_id=player_id,
    )
    
    if out_table_csv:
        Path(out_table_csv).parent.mkdir(parents=True, exist_ok=True)
        df_table.to_csv(out_table_csv, index=False)
    if out_dataset_pt:
        Path(out_dataset_pt).parent.mkdir(parents=True, exist_ok=True)
        torch.save(tensors, out_dataset_pt)
        
    return df_table, tensors


# --------------------------------------------------------------------------- #
# 3. Model Training
# --------------------------------------------------------------------------- #
def split_data_by_game(tensors: dict[str, Any], train_ratio: float = 0.8):
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


def train_clone(
    tensors: dict[str, Any],
    epochs: int = 50,
    batch_size: int = 256,
    lr: float = 1e-3,
    weight_decay: float = 1e-4,
    patience: int = 5,
    train_ratio: float = 0.8,
    out_checkpoint: str = "Model/clone.pt",
) -> dict[str, Any]:
    """
    Trains the Clone model on pre-extracted snapshot tensors.
    Splits by game chronologically to prevent data leakage.
    
    Returns:
        {
            "model": Clone,
            "best_val_move_loss": float,
            "best_val_accuracy": float,
            "checkpoint_path": str,
            "history": list[dict],
        }
    """
    game_ids = tensors["game_ids"]
    unique_games = list(dict.fromkeys(game_ids))
    n_train_games = int(len(unique_games) * train_ratio)
    train_set = set(unique_games[:n_train_games])

    train_idx = torch.tensor([i for i, gid in enumerate(game_ids) if gid in train_set], dtype=torch.long)
    val_idx = torch.tensor([i for i, gid in enumerate(game_ids) if gid not in train_set], dtype=torch.long)

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
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)

    N = len(train_data[0])
    best_val_move = float("inf")
    best_state = None
    patience_counter = 0
    history = []

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

        epoch_record = {
            "epoch": epoch,
            "val_move_loss": val_move.item(),
            "val_time_loss": val_time.item(),
            "val_move_acc": val_acc,
        }
        history.append(epoch_record)

        if val_move.item() < best_val_move:
            best_val_move = val_move.item()
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            patience_counter = 0
        else:
            patience_counter += 1

        if patience_counter >= patience:
            break

    if best_state is not None:
        model.load_state_dict(best_state)
    final_acc = move_accuracy(model, *val_data[:4])

    out_file = Path(out_checkpoint)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out_file)

    return {
        "model": model,
        "best_val_move_loss": best_val_move,
        "best_val_accuracy": final_acc,
        "checkpoint_path": str(out_file),
        "history": history,
    }


# --------------------------------------------------------------------------- #
# 4. Evaluation
# --------------------------------------------------------------------------- #
def evaluate_clone(
    model_or_checkpoint: Clone | str,
    tensors: dict[str, Any],
    split: str = "val",
    train_ratio: float = 0.8,
) -> dict[str, float]:
    """
    Evaluates Clone vs. Plain Maia-3 on held-out game split.
    """
    if isinstance(model_or_checkpoint, str):
        model = Clone()
        model.load_state_dict(torch.load(model_or_checkpoint, map_location="cpu", weights_only=True))
    else:
        model = model_or_checkpoint
    model.eval()

    game_ids = tensors["game_ids"]
    unique_games = list(dict.fromkeys(game_ids))
    n_train = int(len(unique_games) * train_ratio)

    if split == "train":
        eval_set = set(unique_games[:n_train])
    else:
        eval_set = set(unique_games[n_train:])

    idx = torch.tensor([i for i, gid in enumerate(game_ids) if gid in eval_set], dtype=torch.long)
    X = tensors["X"][idx]
    maia_logits = tensors["maia_logits"][idx]
    mask = tensors["mask"][idx]
    target_idx = tensors["target_idx"][idx]
    seconds = tensors["seconds"][idx].clamp(min=0.1)

    with torch.no_grad():
        offsets, time_out = model(X)
        clone_scores = (maia_logits + offsets).masked_fill(mask == 0, float("-inf"))
        maia_scores = maia_logits.masked_fill(mask == 0, float("-inf"))

        clone_nll = F.cross_entropy(clone_scores, target_idx).item()
        maia_nll = F.cross_entropy(maia_scores, target_idx).item()

        clone_pred = clone_scores.argmax(dim=1)
        maia_pred = maia_scores.argmax(dim=1)

        clone_top1 = (clone_pred == target_idx).float().mean().item()
        maia_top1 = (maia_pred == target_idx).float().mean().item()

        # Top-3 accuracy
        _, clone_top3_idx = torch.topk(clone_scores, k=3, dim=1)
        _, maia_top3_idx = torch.topk(maia_scores, k=3, dim=1)
        clone_top3 = (clone_top3_idx == target_idx.unsqueeze(1)).any(dim=1).float().mean().item()
        maia_top3 = (maia_top3_idx == target_idx.unsqueeze(1)).any(dim=1).float().mean().item()

        # Think time NLL
        rows = torch.arange(len(X))
        mean = time_out[rows, target_idx, 0]
        log_std = time_out[rows, target_idx, 1]
        y = torch.log(seconds)
        time_loss = (log_std + (y - mean) ** 2 / (2 * torch.exp(2 * log_std))).mean().item()

    rel_move_gain = ((maia_nll - clone_nll) / maia_nll) * 100

    return {
        "clone_move_nll": clone_nll,
        "maia_move_nll": maia_nll,
        "clone_top1_acc": clone_top1,
        "maia_top1_acc": maia_top1,
        "clone_top3_acc": clone_top3,
        "maia_top3_acc": maia_top3,
        "clone_time_nll": time_loss,
        "rel_move_improvement_pct": rel_move_gain,
    }


# --------------------------------------------------------------------------- #
# 5. Live Position Move & Think-Time Prediction
# --------------------------------------------------------------------------- #
_MAIA_ENGINE = None
_CLONE_MODEL = None

def get_loaded_engine_and_clone(
    clone_weights_path: str = "Model/clone.pt",
    maia_checkpoint: str = "./models/maia3-5m.pt",
):
    global _MAIA_ENGINE, _CLONE_MODEL
    from maia3.uci import Maia3UCIEngine, parse_args

    if _MAIA_ENGINE is None:
        cfg = parse_args(["--model", "maia3-5m", "--checkpoint", maia_checkpoint, "--use-uci-history"])
        _MAIA_ENGINE = Maia3UCIEngine(cfg)
        _MAIA_ENGINE.ensure_model_loaded()

    if _CLONE_MODEL is None:
        _CLONE_MODEL = Clone()
        weights_file = Path(clone_weights_path)
        if weights_file.is_file():
            _CLONE_MODEL.load_state_dict(torch.load(weights_file, map_location="cpu", weights_only=True))
        _CLONE_MODEL.eval()

    return _MAIA_ENGINE, _CLONE_MODEL


def predict_move(
    board: chess.Board,
    elo: int = 1800,
    own_clock: float = 600.0,
    opp_clock: float = 600.0,
    opp_last_think_s: float = 0.0,
    avg_think_s: float = 5.0,
    clone_weights_path: str = "Model/clone.pt",
    maia_checkpoint: str = "./models/maia3-5m.pt",
    temperature: float = 1.0,
) -> dict[str, Any]:
    """
    Predicts the next move and think time for the clone in a live game.
    
    Returns:
        {
            "chosen_uci": str,
            "chosen_san": str,
            "think_seconds": float,
            "candidates": list[dict],
        }
    """
    from maia3.dataset import get_legal_moves_mask, tokenize_board

    engine, clone = get_loaded_engine_and_clone(clone_weights_path, maia_checkpoint)
    
    # Sync board to engine
    engine.board = board.copy()
    engine.self_elo = elo
    engine.oppo_elo = elo
    history = deque(maxlen=engine.cfg.history)
    replay = chess.Board()
    history.append(tokenize_board(replay))
    for mv in board.move_stack:
        replay.push(mv)
        history.append(tokenize_board(replay))
    engine.history = history

    mask = get_legal_moves_mask(engine.board, engine.all_moves_dict)
    device = torch.device(engine.cfg.device)
    tokens = engine._tokens_from_history(engine.history).unsqueeze(0).to(device)
    elos = torch.tensor([elo], dtype=torch.long, device=device)

    with torch.no_grad():
        logits_move, _, _ = engine.model(tokens, elos, elos)
    logits = logits_move[0].float().cpu()

    moves, vals = [], []
    for idx in mask.nonzero(as_tuple=False).flatten().tolist():
        mv = engine._move_from_index(idx)
        if mv is not None:
            moves.append(mv)
            vals.append(logits[idx])

    if not moves:
        return {"chosen_uci": None, "chosen_san": None, "think_seconds": 0.0, "candidates": []}

    if len(moves) > 64:
        top_idx = torch.topk(torch.stack(vals), 64).indices.tolist()
        moves = [moves[i] for i in top_idx]
        vals = [vals[i] for i in top_idx]

    vals_tensor = torch.stack(vals)
    probs_tensor = torch.softmax(vals_tensor, dim=0)
    order = torch.argsort(vals_tensor, descending=True)
    rank = torch.empty(len(moves))
    rank[order] = torch.arange(1, len(moves) + 1, dtype=torch.float)

    # 12 context features
    ply = board.fullmove_number * 2 - (2 if board.turn == chess.WHITE else 1)
    context = compute_context_features(
        board=board,
        own_clock=own_clock,
        opp_clock=opp_clock,
        ply=ply,
        opp_last_think_s=opp_last_think_s,
        avg_think_s=avg_think_s,
        num_legal_moves=len(moves),
        probs_tensor=probs_tensor,
    )

    rows = []
    for i, mv in enumerate(moves):
        m_feats = compute_move_features(
            board=board,
            move=mv,
            maia_logit=vals_tensor[i].item(),
            maia_prob=probs_tensor[i].item(),
            maia_log_rank=math.log(rank[i].item()),
        )
        rows.append(m_feats + context)

    X = torch.zeros(1, 64, 28)
    X[0, : len(moves)] = torch.tensor(rows, dtype=torch.float)
    packed = torch.zeros(1, 64)
    packed[0, : len(moves)] = vals_tensor
    mask_tensor = torch.zeros(1, 64)
    mask_tensor[0, : len(moves)] = 1.0

    with torch.no_grad():
        offsets, time_out = clone(X)

    scores = (packed + offsets).masked_fill(mask_tensor == 0, float("-inf"))
    n = len(moves)

    # Move probabilities
    if temperature <= 0.0:
        slot = scores[0, :n].argmax().item()
    else:
        sample_probs = torch.softmax(scores[0, :n] / temperature, dim=0)
        slot = torch.multinomial(sample_probs, 1).item()

    # Think time sampling
    mean = time_out[0, slot, 0].item()
    log_std = time_out[0, slot, 1].item()
    try:
        think_s = math.exp(mean + math.exp(log_std) * random.gauss(0, 1))
    except OverflowError:
        think_s = own_clock
    think_s = min(max(think_s, 0.1), own_clock)

    # Candidate list
    clone_probs = torch.softmax(scores[0, :n], dim=0)
    candidates = []
    for i, mv in enumerate(moves):
        candidates.append({
            "san": board.san(mv),
            "uci": mv.uci(),
            "clone_prob": round(clone_probs[i].item(), 4),
            "maia_prob": round(probs_tensor[i].item(), 4),
            "offset": round(offsets[0, i].item(), 4),
        })
    candidates.sort(key=lambda c: c["clone_prob"], reverse=True)

    chosen_move = moves[slot]
    return {
        "chosen_uci": chosen_move.uci(),
        "chosen_san": board.san(chosen_move),
        "think_seconds": round(think_s, 2),
        "candidates": candidates,
    }


# --------------------------------------------------------------------------- #
# 6. Complete End-to-End Helper
# --------------------------------------------------------------------------- #
def train_from_csv(
    csv_path: str,
    out_model_path: str = "Model/clone.pt",
    epochs: int = 50,
    batch_size: int = 128,
    train_batch_size: int = 256,
    limit_games: Optional[int] = None,
    checkpoint_path: str = "./models/maia3-5m.pt",
) -> dict[str, Any]:
    """
    End-to-end wrapper: CSV -> Snapshots -> Maia Logits -> Train Clone -> Evaluate.
    """
    _, tensors = extract_maia_logits(
        csv_path=csv_path,
        checkpoint_path=checkpoint_path,
        batch_size=batch_size,
        limit_games=limit_games,
    )
    
    train_result = train_clone(
        tensors=tensors,
        epochs=epochs,
        batch_size=train_batch_size,
        out_checkpoint=out_model_path,
    )
    
    eval_metrics = evaluate_clone(
        model_or_checkpoint=train_result["model"],
        tensors=tensors,
        split="val",
    )
    
    return {
        "model_path": out_model_path,
        "train_metrics": train_result,
        "evaluation": eval_metrics,
    }
