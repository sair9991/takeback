"""
pipeline/maia_extractor.py - Run Maia-3 on game snapshots to extract logits and assemble tensors.

Outputs:
  1. snapshots_with_logits.csv: A tabular view of snapshots with Maia logits, probabilities, and ranks.
  2. snapshots_dataset.pt: PyTorch dictionary with tensors:
       - X: (N, 64, 28)
       - maia_logits: (N, 64)
       - mask: (N, 64)
       - target_idx: (N,)
       - seconds: (N,)
       - time_label_valid: (N,)
       - metadata: game_ids, plies, player_colors, move_sans, move_ucis
"""

from __future__ import annotations

import csv
import io
import math
import os
import sys
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import chess
import chess.pgn
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F

MODEL_DIR = Path(__file__).resolve().parent
ROOT = MODEL_DIR.parent
for _path in (str(ROOT / "maia3"), str(ROOT), str(MODEL_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from maia3.dataset import get_historical_tokens, tokenize_board
from maia3.model_registry import apply_model_config, resolve_checkpoint_path, resolve_model_spec
from maia3.uci import load_model
from maia3.utils import get_all_possible_moves, mirror_move

try:
    from features import compute_context_features, compute_move_features
except ImportError:
    from Model.features import compute_context_features, compute_move_features
from snapshots import CLK_RE, DropGame, parse_clock, parse_time_control, _to_int, make_game_id

MAX_SLOTS = 64
FEATURE_DIM = 28


def load_maia3_model(
    checkpoint_path: str = "./models/maia3-5m.pt",
    model_name: str = "maia3-5m",
    device: Optional[str] = None,
):
    if device is None:
        device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")

    spec = resolve_model_spec(model_name)
    if not Path(checkpoint_path).is_file():
        local_ckpt = ROOT / "models" / "maia3-5m.pt"
        if local_ckpt.is_file():
            checkpoint_path = str(local_ckpt)
        else:
            checkpoint_path = resolve_checkpoint_path(spec)
    cfg = SimpleNamespace(
        device=device,
        trust_checkpoint=True,
        checkpoint_path=checkpoint_path,
        use_amp=False,
        history=8,
    )
    apply_model_config(cfg, spec)
    model = load_model(cfg)
    model.eval()
    return model, cfg, device


def replay_game_to_snapshots(row: dict, game_order: int = 0) -> list[dict]:
    """Replays a single game row, tracking full board history for Maia-3."""
    color = str(row["player_color"]).strip().lower()
    if color not in ("white", "black"):
        raise DropGame("bad_color", repr(row["player_color"]))

    base, inc = parse_time_control(row["time_control"])
    player_elo = _to_int(row["player_elo"])
    opp_elo = _to_int(row["opponent_elo"])
    game_id = make_game_id(row)

    game = chess.pgn.read_game(io.StringIO(row.get("moves", "")))
    if game is None or game.errors:
        raise DropGame("unparseable_moves")

    board = game.board()
    nodes = list(game.mainline())
    if not nodes:
        raise DropGame("unparseable_moves", "no moves")

    # Clocks and think times
    last_clock = {"white": base, "black": base}
    last_think = {"white": 0.0, "black": 0.0}
    think_history = {"white": [], "black": []}

    snapshots = []
    board_history_deque = deque(maxlen=8)

    for ply, node in enumerate(nodes, start=1):
        mover_side = "white" if board.turn == chess.WHITE else "black"
        clock_after = parse_clock(node.comment)
        if clock_after is None:
            raise DropGame("missing_clocks", f"ply {ply}")

        clock_before = last_clock[mover_side]
        seconds_spent = round(clock_before - clock_after + inc, 3)
        if seconds_spent < -0.15:
            raise DropGame("clock_increased", f"ply {ply}: {clock_before} -> {clock_after}")
        seconds_spent = max(seconds_spent, 0.0)

        # Before making the move, store the tokenized board for history
        tokenized_current = tokenize_board(board)
        board_history_deque.append(tokenized_current)

        if mover_side == color:
            opp_side = "black" if mover_side == "white" else "white"
            mover_thinks = think_history[mover_side]
            avg_think = sum(mover_thinks) / len(mover_thinks) if mover_thinks else 0.0
            snap = {
                "game_id": game_id,
                "game_order": game_order,
                "player_id": str(row["player_id"]).strip(),
                "date": str(row["date"]).strip(),
                "player_color": color,
                "time_control": str(row["time_control"]).strip(),
                "base_seconds": base,
                "increment_seconds": inc,
                "ply": ply,
                "move_number": (ply + 1) // 2,
                "board_fen": board.fen(),
                "board_obj": board.copy(),
                "board_history": list(board_history_deque),
                "move_san": board.san(node.move),
                "move_uci": node.move.uci(),
                "seconds_spent": seconds_spent,
                "log_seconds": round(math.log(max(seconds_spent, 0.1)), 4),
                "time_label_valid": ply > 2,
                "clock_before": clock_before,
                "clock_after": clock_after,
                "opp_clock": last_clock[opp_side],
                "own_last_think_s": last_think[mover_side],
                "opp_last_think_s": last_think[opp_side],
                "avg_think_s": avg_think,
                "player_elo": player_elo,
                "opponent_elo": opp_elo,
                "opponent": str(row["opponent"]).strip(),
                "result": str(row["result"]).strip(),
            }
            snapshots.append(snap)

        last_clock[mover_side] = clock_after
        last_think[mover_side] = seconds_spent
        think_history[mover_side].append(seconds_spent)
        board.push(node.move)

    return snapshots


def extract_snapshots_and_maia_logits(
    csv_path: Optional[str] = None,
    checkpoint_path: str = "./models/maia3-5m.pt",
    model_name: str = "maia3-5m",
    batch_size: int = 128,
    limit_games: Optional[int] = None,
    player_id: Optional[str] = None,
    rows: Optional[list[dict]] = None,
) -> tuple[pd.DataFrame, dict[str, torch.Tensor]]:
    """
    Parses games (from CSV or in-memory rows), runs Maia-3 in batches, and builds both:
    1. A pandas DataFrame table of snapshots with logits
    2. PyTorch tensors (X, maia_logits, mask, target_idx, seconds, time_label_valid)
    """
    if rows is None:
        if not csv_path:
            raise ValueError("Must provide either csv_path or rows.")
        print(f"Loading games from {csv_path}...")
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    else:
        print(f"Processing {len(rows)} in-memory games...")

    if player_id:
        rows = [r for r in rows if r.get("player_id", "").strip().lower() == player_id.lower()]
    if limit_games:
        rows = rows[:limit_games]

    print(f"Replaying {len(rows)} games to extract snapshots...")
    raw_snapshots = []
    seen_games = set()
    kept_count = 0
    drop_count = 0

    for order, row in enumerate(rows):
        gid = make_game_id(row)
        if gid in seen_games:
            continue
        try:
            snaps = replay_game_to_snapshots(row, order)
            seen_games.add(gid)
            raw_snapshots.extend(snaps)
            kept_count += 1
        except DropGame:
            drop_count += 1

    print(f"Total games kept: {kept_count}, dropped: {drop_count}. Total snapshots: {len(raw_snapshots)}")

    # Initialize Maia-3
    print("Initializing Maia-3 model...")
    model, cfg, device = load_maia3_model(checkpoint_path=checkpoint_path, model_name=model_name)
    all_moves = get_all_possible_moves()
    all_moves_dict = {m: i for i, m in enumerate(all_moves)}

    N = len(raw_snapshots)
    tensor_X = torch.zeros((N, MAX_SLOTS, FEATURE_DIM), dtype=torch.float32)
    tensor_maia_logits = torch.zeros((N, MAX_SLOTS), dtype=torch.float32)
    tensor_mask = torch.zeros((N, MAX_SLOTS), dtype=torch.float32)
    tensor_target_idx = torch.zeros((N,), dtype=torch.long)
    tensor_seconds = torch.zeros((N,), dtype=torch.float32)
    tensor_time_valid = torch.zeros((N,), dtype=torch.bool)

    table_rows = []

    print(f"Running Maia-3 batch inference on {N} snapshots (batch size {batch_size}, device {device})...")

    for b_start in range(0, N, batch_size):
        b_end = min(b_start + batch_size, N)
        batch_snaps = raw_snapshots[b_start:b_end]
        cur_batch_len = len(batch_snaps)

        # Build batched token tensor
        batch_tokens_list = []
        batch_self_elos = []
        batch_oppo_elos = []

        for s in batch_snaps:
            tokens = get_historical_tokens(
                deque(s["board_history"], maxlen=8),
                cfg,
                base=0.0,
                inc=0.0,
                clk_left_before=0.0,
                clk_ponder=0.0,
            )
            batch_tokens_list.append(tokens)
            batch_self_elos.append(s["player_elo"])
            batch_oppo_elos.append(s["opponent_elo"])

        tokens_tensor = torch.stack(batch_tokens_list).to(device)
        self_elos_tensor = torch.tensor(batch_self_elos, dtype=torch.long, device=device)
        oppo_elos_tensor = torch.tensor(batch_oppo_elos, dtype=torch.long, device=device)

        with torch.no_grad():
            logits_move, _, _ = model(tokens_tensor, self_elos_tensor, oppo_elos_tensor)
            logits_move = logits_move.cpu()

        # Process each snapshot in the batch
        for i_in_batch, s in enumerate(batch_snaps):
            global_idx = b_start + i_in_batch
            board: chess.Board = s["board_obj"]
            played_uci = s["move_uci"]
            pos_logits = logits_move[i_in_batch]

            # Collect legal moves and their Maia logits
            legal_moves = list(board.legal_moves)
            move_records = []
            for m in legal_moves:
                m_uci = m.uci() if board.turn == chess.WHITE else mirror_move(m.uci())
                m_idx = all_moves_dict.get(m_uci)
                logit_val = float(pos_logits[m_idx].item()) if m_idx is not None else -100.0
                move_records.append((m, logit_val))

            # Sort descending by logit
            move_records.sort(key=lambda r: r[1], reverse=True)

            # Check if played move is present
            target_found = any(m.uci() == played_uci for m, _ in move_records)
            if not target_found:
                # Fallback if played move wasn't in legal moves
                print(f"Warning: played move {played_uci} not found in legal moves at snapshot {global_idx}")

            # Cap at MAX_SLOTS (64) while guaranteeing target move is included
            if len(move_records) > MAX_SLOTS:
                target_rec = next((r for r in move_records if r[0].uci() == played_uci), None)
                trimmed = move_records[:MAX_SLOTS]
                if target_rec and target_rec not in trimmed:
                    trimmed[-1] = target_rec
                move_records = trimmed

            num_valid = len(move_records)
            logits_arr = np.array([r[1] for r in move_records], dtype=np.float32)
            # Softmax probabilities over legal moves
            exp_logits = np.exp(logits_arr - np.max(logits_arr))
            probs_arr = exp_logits / np.sum(exp_logits)

            # Context features (12)
            context_feats = compute_context_features(
                board=board,
                own_clock=s["clock_before"],
                opp_clock=s["opp_clock"],
                ply=s["ply"],
                opp_last_think_s=s["opp_last_think_s"],
                avg_think_s=s["avg_think_s"],
                num_legal_moves=num_valid,
                probs_tensor=torch.from_numpy(probs_arr),
            )

            target_slot = -1
            top1_uci = move_records[0][0].uci()
            top1_prob = float(probs_arr[0])

            target_logit = 0.0
            target_prob = 0.0
            target_rank = 0

            for slot_idx, (m, logit_val) in enumerate(move_records):
                prob_val = float(probs_arr[slot_idx])
                rank_val = slot_idx + 1  # 1-based rank
                log_rank_val = math.log(rank_val)

                if m.uci() == played_uci:
                    target_slot = slot_idx
                    target_logit = logit_val
                    target_prob = prob_val
                    target_rank = rank_val

                move_feats = compute_move_features(
                    board=board,
                    move=m,
                    maia_logit=logit_val,
                    maia_prob=prob_val,
                    maia_log_rank=log_rank_val,
                )
                full_feats = move_feats + context_feats

                tensor_X[global_idx, slot_idx] = torch.tensor(full_feats, dtype=torch.float32)
                tensor_maia_logits[global_idx, slot_idx] = logit_val
                tensor_mask[global_idx, slot_idx] = 1.0

            if target_slot == -1:
                target_slot = 0  # Fallback safety

            tensor_target_idx[global_idx] = target_slot
            tensor_seconds[global_idx] = s["seconds_spent"]
            tensor_time_valid[global_idx] = s["time_label_valid"]

            # Save tabular snapshot record
            table_rows.append({
                "game_id": s["game_id"],
                "game_order": s["game_order"],
                "player_id": s["player_id"],
                "date": s["date"],
                "player_color": s["player_color"],
                "ply": s["ply"],
                "move_number": s["move_number"],
                "board_fen": s["board_fen"],
                "n_legal_moves": num_valid,
                "played_move_san": s["move_san"],
                "played_move_uci": played_uci,
                "seconds_spent": s["seconds_spent"],
                "log_seconds": s["log_seconds"],
                "time_label_valid": s["time_label_valid"],
                "clock_before": s["clock_before"],
                "opp_clock": s["opp_clock"],
                "player_elo": s["player_elo"],
                "opponent_elo": s["opponent_elo"],
                "target_slot_idx": target_slot,
                "maia_target_logit": round(target_logit, 4),
                "maia_target_prob": round(target_prob, 5),
                "maia_target_rank": target_rank,
                "maia_top1_move": top1_uci,
                "maia_top1_prob": round(top1_prob, 5),
                "maia_agrees": (target_slot == 0),
            })

        if (b_start // batch_size) % 10 == 0 or b_end == N:
            print(f"  Processed {b_end}/{N} snapshots ({b_end / N * 100:.1f}%)")

    df_table = pd.DataFrame(table_rows)
    tensors = {
        "X": tensor_X,
        "maia_logits": tensor_maia_logits,
        "mask": tensor_mask,
        "target_idx": tensor_target_idx,
        "seconds": tensor_seconds,
        "time_label_valid": tensor_time_valid,
        "game_ids": [s["game_id"] for s in raw_snapshots],
        "plies": torch.tensor([s["ply"] for s in raw_snapshots], dtype=torch.long),
        "dates": [s["date"] for s in raw_snapshots],
    }

    return df_table, tensors


def run(csv_path, out_csv=None, out_pt=None, limit_games=None, batch_size=128):
    out_csv = out_csv or str(ROOT / "snapshots_with_logits.csv")
    out_pt = out_pt or str(ROOT / "snapshots_dataset.pt")
    df_table, tensors = extract_snapshots_and_maia_logits(
        csv_path=csv_path, limit_games=limit_games, batch_size=batch_size,
    )
    print(f"Saving table to {out_csv}...")
    df_table.to_csv(out_csv, index=False)
    print(f"Saving tensors to {out_pt}...")
    torch.save(tensors, out_pt)
    print("Done! Table shape:", df_table.shape)
    print("Tensor X shape:", tensors["X"].shape)
    return out_pt


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default=str(ROOT / "model_dev" / "stuffyness.csv"))
    parser.add_argument("--out-csv", default=str(ROOT / "snapshots_with_logits.csv"))
    parser.add_argument("--out-pt", default=str(ROOT / "snapshots_dataset.pt"))
    parser.add_argument("--limit-games", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=128)
    args = parser.parse_args()

    run(args.csv, args.out_csv, args.out_pt, args.limit_games, args.batch_size)

