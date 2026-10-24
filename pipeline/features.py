"""
pipeline/features.py - Compute the 28 features per legal move.

Directly aligned with Model/play_clone.py and Model/implementation.py:
  16 move features:
    0: Maia logit
    1: Maia prob
    2: ln(rank) (1-based)
    3: is_capture
    4: gives_check
    5: is_castling
    6: is_promotion
    7-12: one-hot for [pawn, knight, bishop, rook, queen, king]
    13: retreat (not forward and frm != to)
    14: forward
    15: hung / attacked_and_undefended

  12 context features:
    16: own = own_clock / 600.0
    17: opp = opp_clock / 600.0
    18: ply / 100.0
    19: float(board.is_check())
    20: n / 64.0
    21: ln(1 + opp_last_think_s)
    22: entropy / ln(max(n, 2))
    23: max(probs)
    24: mat / 10.0
    25: ln(1 + avg_think_s)
    26: (1 - own) - min(1.0, ply / 40.0)
    27: min(own, opp)

Total: 28 features.
"""

from __future__ import annotations

import math
import chess
import torch

PIECE_TYPES = [chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN, chess.KING]
VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}


def compute_material_balance(board: chess.Board) -> float:
    mat = 0
    for piece in board.piece_map().values():
        v = VALUES.get(piece.piece_type, 0)
        mat += v if piece.color == board.turn else -v
    return mat / 10.0


def compute_context_features(
    board: chess.Board,
    own_clock: float,
    opp_clock: float,
    ply: int,
    opp_last_think_s: float,
    avg_think_s: float,
    num_legal_moves: int,
    probs_tensor: torch.Tensor,
) -> list[float]:
    n = num_legal_moves
    own = min(max(own_clock / 600.0, 0.0), 1.0)
    opp = min(max(opp_clock / 600.0, 0.0), 1.0)
    mat = compute_material_balance(board)

    # Entropy
    clamped_probs = probs_tensor.clamp(min=1e-8)
    entropy = -(probs_tensor * torch.log(clamped_probs)).sum().item()
    norm_entropy = entropy / math.log(max(n, 2))
    max_prob = float(probs_tensor.max().item())

    return [
        own,
        opp,
        ply / 100.0,
        float(board.is_check()),
        n / 64.0,
        math.log1p(max(opp_last_think_s, 0.0)),
        norm_entropy,
        max_prob,
        mat,
        math.log1p(max(avg_think_s, 0.0)),
        (1.0 - own) - min(1.0, ply / 40.0),
        min(own, opp),
    ]


def compute_move_features(
    board: chess.Board,
    move: chess.Move,
    maia_logit: float,
    maia_prob: float,
    maia_log_rank: float,
) -> list[float]:
    piece = board.piece_at(move.from_square)
    frm = chess.square_rank(move.from_square)
    to = chess.square_rank(move.to_square)
    forward = to > frm if board.turn == chess.WHITE else to < frm

    # Hung: attacked and undefended after move
    after = board.copy(stack=False)
    after.push(move)
    hung = after.is_attacked_by(after.turn, move.to_square) and not after.is_attacked_by(not after.turn, move.to_square)

    one_hot = [1.0 if piece and piece.piece_type == kind else 0.0 for kind in PIECE_TYPES]

    return [
        float(maia_logit),
        float(maia_prob),
        float(maia_log_rank),
        float(board.is_capture(move)),
        float(board.gives_check(move)),
        float(board.is_castling(move)),
        float(move.promotion is not None),
        *one_hot,
        float(not forward and frm != to),
        float(forward),
        float(hung),
    ]
