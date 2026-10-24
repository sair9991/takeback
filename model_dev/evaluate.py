"""
evaluate.py - Test and evaluate the trained Maia Adapter model.

Usage:
  1. Evaluate trained model on held-out test dataset:
     python evaluate.py --checkpoint mlp_adapter_best.pt --dataset snapshots_dataset.pt

  2. Test a single chess position / FEN:
     python evaluate.py --fen "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1" --clock 580 --opp-clock 595
"""

from __future__ import annotations

import argparse
import math
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import chess
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader

from maia3.dataset import get_historical_tokens, tokenize_board
from maia3.model_registry import apply_model_config, resolve_model_spec
from maia3.uci import load_model
from maia3.utils import get_all_possible_moves, mirror_move

from pipeline.dataset import split_snapshots_by_game
from pipeline.features import compute_context_features, compute_move_features
from pipeline.model import MaiaAdapterMLP
from pipeline.train import evaluate_model, compute_constant_time_baseline


def evaluate_checkpoint_on_test_set(checkpoint_path: str, dataset_path: str, device: str = "cpu"):
    print(f"Loading dataset from {dataset_path}...")
    tensors = torch.load(dataset_path, map_location="cpu", weights_only=False)
    _, _, test_ds = split_snapshots_by_game(tensors, 0.8, 0.1, 0.1)
    test_loader = DataLoader(test_ds, batch_size=256, shuffle=False)

    print(f"Loading model checkpoint from {checkpoint_path}...")
    model = MaiaAdapterMLP(input_dim=28, hidden_dim=64).to(device)
    ckpt = torch.load(checkpoint_path, map_location=device, weights_only=True)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()

    # Evaluate Plain Maia-3
    maia_metrics = evaluate_model(None, test_loader, device)

    # Evaluate Adapter Model
    model_metrics = evaluate_model(model, test_loader, device)

    rel_move_gain = ((maia_metrics["move_nll"] - model_metrics["move_nll"]) / maia_metrics["move_nll"]) * 100
    rel_time_gain = ((maia_metrics["time_nll"] - model_metrics["time_nll"]) / maia_metrics["time_nll"]) * 100

    print("\n" + "=" * 65)
    print("HELD-OUT TEST SET EVALUATION REPORT")
    print("=" * 65)
    print(f"{'Metric':<25} | {'Plain Maia-3':<15} | {'Your Adapter MLP':<15}")
    print("-" * 65)
    print(f"{'Move NLL (lower is better)':<25} | {maia_metrics['move_nll']:<15.4f} | {model_metrics['move_nll']:<15.4f}")
    print(f"{'Top-1 Move Accuracy':<25} | {maia_metrics['top1_acc']*100:<14.2f}% | {model_metrics['top1_acc']*100:<14.2f}%")
    print(f"{'Top-3 Move Accuracy':<25} | {maia_metrics['top3_acc']*100:<14.2f}% | {model_metrics['top3_acc']*100:<14.2f}%")
    print(f"{'Time NLL (lower is better)':<25} | {maia_metrics['time_nll']:<15.4f} | {model_metrics['time_nll']:<15.4f}")
    print("-" * 65)
    print(f"Relative Move NLL Improvement: {rel_move_gain:+.2f}%")
    print(f"Relative Time NLL Improvement: {rel_time_gain:+.2f}%")
    print("=" * 65)


def test_single_position(
    fen: str,
    checkpoint_path: str = "mlp_adapter_best.pt",
    maia_checkpoint: str = "./models/maia3-5m.pt",
    own_clock: float = 450.0,
    opp_clock: float = 480.0,
    base_seconds: float = 600.0,
    device: str = "cpu",
):
    board = chess.Board(fen)
    mover_color = "white" if board.turn == chess.WHITE else "black"

    # 1. Load Maia
    spec = resolve_model_spec("maia3-5m")
    cfg = SimpleNamespace(device=device, trust_checkpoint=True, checkpoint_path=maia_checkpoint, use_amp=False, history=8)
    apply_model_config(cfg, spec)
    maia_model = load_model(cfg).to(device)
    maia_model.eval()

    all_moves = get_all_possible_moves()
    all_moves_dict = {m: i for i, m in enumerate(all_moves)}

    # Historical tokens for FEN (padded)
    history = deque([tokenize_board(board)], maxlen=8)
    tokens = get_historical_tokens(history, cfg, base=0.0, inc=0.0, clk_left_before=0.0, clk_ponder=0.0).unsqueeze(0).to(device)
    self_elos = torch.tensor([1800], dtype=torch.long, device=device)
    oppo_elos = torch.tensor([1800], dtype=torch.long, device=device)

    with torch.no_grad():
        logits_move, _, _ = maia_model(tokens, self_elos, oppo_elos)
        logits_move = logits_move[0].cpu()

    # 2. Extract legal moves & features
    legal_moves = list(board.legal_moves)
    records = []
    for m in legal_moves:
        m_uci = m.uci() if board.turn == chess.WHITE else mirror_move(m.uci())
        idx = all_moves_dict.get(m_uci)
        logit_val = float(logits_move[idx].item()) if idx is not None else -100.0
        records.append((m, logit_val))

    records.sort(key=lambda r: r[1], reverse=True)
    num_moves = min(len(records), 64)
    records = records[:num_moves]

    import numpy as np
    logits_arr = np.array([r[1] for r in records], dtype=np.float32)
    exp_l = np.exp(logits_arr - np.max(logits_arr))
    maia_probs = exp_l / np.sum(exp_l)

    context_feats = compute_context_features(
        board=board,
        own_clock=own_clock,
        opp_clock=opp_clock,
        base_seconds=base_seconds,
        increment_seconds=0.0,
        ply=20,
        own_last_think_s=5.0,
        opp_last_think_s=4.0,
        player_color=mover_color,
    )

    X = torch.zeros((1, 64, 28))
    maia_logits_tensor = torch.zeros((1, 64))
    mask_tensor = torch.zeros((1, 64))

    for i, (m, logit_val) in enumerate(records):
        prob_val = float(maia_probs[i])
        rank_val = i + 1
        move_feats = compute_move_features(board, m, logit_val, prob_val, math.log(rank_val))
        X[0, i] = torch.tensor(move_feats + context_feats, dtype=torch.float32)
        maia_logits_tensor[0, i] = logit_val
        mask_tensor[0, i] = 1.0

    # 3. Load MLP Adapter
    adapter = MaiaAdapterMLP(input_dim=28, hidden_dim=64).to(device)
    ckpt = torch.load(checkpoint_path, map_location=device, weights_only=True)
    adapter.load_state_dict(ckpt["model_state_dict"])
    adapter.eval()

    with torch.no_grad():
        adj_logits, clone_probs, mu, sigma, offset = adapter(X.to(device), maia_logits_tensor.to(device), mask_tensor.to(device))
        clone_probs = clone_probs[0].cpu().numpy()
        mu = mu[0].cpu().numpy()
        sigma = sigma[0].cpu().numpy()
        offset = offset[0].cpu().numpy()

    print("\n" + "=" * 75)
    print(f"POSITION EVALUATION ({mover_color.upper()} to move)")
    print(f"FEN: {fen}")
    print(f"Clocks: Own={own_clock:.1f}s, Opp={opp_clock:.1f}s")
    print("=" * 75)
    print(f"{'Move (SAN)':<12} | {'Maia Prob':<12} | {'Clone Prob':<12} | {'Offset d(m)':<12} | {'Pred Think Time':<15}")
    print("-" * 75)

    # Top 5 moves by clone probability
    clone_order = np.argsort(-clone_probs[:num_moves])
    for rank, idx in enumerate(clone_order[:6], 1):
        m, _ = records[idx]
        san = board.san(m)
        m_prob = maia_probs[idx] * 100
        c_prob = clone_probs[idx] * 100
        off = offset[idx]
        # Median think time is exp(mu) seconds
        pred_sec = math.exp(mu[idx])
        print(f"{san:<12} | {m_prob:>10.2f}% | {c_prob:>10.2f}% | {off:>+11.3f} | {pred_sec:>10.1f} s")
    print("=" * 75)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", default="mlp_adapter_best.pt", help="Adapter weights")
    parser.add_argument("--dataset", default="snapshots_dataset.pt", help="Dataset path")
    parser.add_argument("--fen", default=None, help="Custom FEN to test")
    parser.add_argument("--clock", type=float, default=450.0, help="Own clock in seconds")
    parser.add_argument("--opp-clock", type=float, default=480.0, help="Opponent clock in seconds")
    args = parser.parse_args()

    device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")

    if args.fen:
        test_single_position(args.fen, checkpoint_path=args.checkpoint, own_clock=args.clock, opp_clock=args.opp_clock, device=device)
    else:
        evaluate_checkpoint_on_test_set(args.checkpoint, args.dataset, device=device)


if __name__ == "__main__":
    main()

