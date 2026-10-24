"""
tests/test_pipeline.py - Verification tests corresponding to PRD Section 9.

Tests:
  1. Zero-offset test: with move_head initialized to 0, model output matches Maia-3's probabilities exactly.
  2. Feature count test: tensor feature dimension is exactly 28.
  3. Split integrity test: train, val, and test splits share 0 game IDs.
  4. Clock arithmetic test: first sample game plies 1 & 2 have exact think times (1.2s, 22.7s).
"""

from __future__ import annotations

import math
import pytest
import torch
import torch.nn.functional as F

from pipeline.dataset import split_snapshots_by_game
from pipeline.features import compute_context_features, compute_move_features
from pipeline.model import MaiaAdapterMLP
from snapshots import build_game_snapshots, load_rows


def test_zero_offset_exact_match():
    """With move head initialized to zeros, output probabilities must equal Maia-3 probabilities exactly."""
    model = MaiaAdapterMLP(input_dim=28, hidden_dim=64)
    model.eval()

    B, M = 4, 30
    X = torch.randn(B, 64, 28)
    maia_logits = torch.randn(B, 64)
    mask = torch.zeros(B, 64)
    mask[:, :M] = 1.0  # M legal moves, rest padding

    with torch.no_grad():
        adjusted_logits, probs, _, _, offset = model(X, maia_logits, mask)

        # Offset must be zero everywhere
        assert torch.allclose(offset, torch.zeros_like(offset), atol=1e-7)

        # Direct Maia probabilities
        bool_mask = mask.bool()
        direct_maia_logits = torch.where(bool_mask, maia_logits, torch.full_like(maia_logits, float("-inf")))
        direct_probs = F.softmax(direct_maia_logits, dim=-1)

        diff = (probs - direct_probs).abs().max().item()
        assert diff < 1e-6, f"Probabilities differed by {diff}"


def test_feature_count():
    """Feature vector length per legal move must be exactly 28."""
    import chess
    board = chess.Board()
    move = chess.Move.from_uci("e2e4")

    move_feats = compute_move_features(board, move, maia_logit=15.0, maia_prob=0.4, maia_log_rank=0.0)
    assert len(move_feats) == 16, f"Expected 16 move features, got {len(move_feats)}"

    context_feats = compute_context_features(
        board=board,
        own_clock=598.8,
        opp_clock=600.0,
        ply=1,
        opp_last_think_s=0.0,
        avg_think_s=0.0,
        num_legal_moves=20,
        probs_tensor=torch.full((20,), 0.05),
    )
    assert len(context_feats) == 12, f"Expected 12 context features, got {len(context_feats)}"
    assert len(move_feats + context_feats) == 28


def test_clock_arithmetic():
    """In the first sample game, White's e4 took 1.2s and Black's c6 took 22.7s."""
    rows = load_rows("stuffyness.csv")
    first_game = rows[0]
    snaps = build_game_snapshots(first_game)

    # First game player_color is Black, so first snapshot is ply 2 (move 1... c6)
    c6_snap = snaps[0]
    assert c6_snap.ply == 2
    assert c6_snap.move_san == "c6"
    assert c6_snap.seconds_spent == 22.7
    assert c6_snap.opp_last_think_s == 1.2


def test_split_integrity():
    """Split integrity: no game ID appears in more than one split."""
    dummy_games = [f"game_{i // 10}" for i in range(100)]  # 10 games, 10 moves each
    dummy_tensors = {
        "X": torch.zeros((100, 64, 28)),
        "maia_logits": torch.zeros((100, 64)),
        "mask": torch.zeros((100, 64)),
        "target_idx": torch.zeros((100,), dtype=torch.long),
        "seconds": torch.zeros((100,)),
        "time_label_valid": torch.zeros((100,), dtype=torch.bool),
        "game_ids": dummy_games,
        "plies": torch.arange(100),
    }

    train_ds, val_ds, test_ds = split_snapshots_by_game(dummy_tensors, 0.8, 0.1, 0.1)

    train_set = set(train_ds.game_ids)
    val_set = set(val_ds.game_ids)
    test_set = set(test_ds.game_ids)

    assert len(train_set.intersection(val_set)) == 0
    assert len(train_set.intersection(test_set)) == 0
    assert len(val_set.intersection(test_set)) == 0

