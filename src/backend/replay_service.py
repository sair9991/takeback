"""
src/backend/replay_service.py - Replay Move Prediction Service for Frontend Board Analysis.

Allows users to query the trained Clone model from any game state as they replay a game
in the frontend using a standard FEN string.

Function:
    replay_clone_move(
        fen: str,
        clone_color: str | chess.Color,
        clone_time: float,
        weights_path: str | Path,
        params: Optional[dict[str, Any]] = None,
        **kwargs,
    ) -> ReplayMoveResult

Inputs:
    - fen: FEN string of the current game board (e.g. 'r1bqkbnr/pppp1ppp/2n5/4p3/3PP3/5N2/PPP2PPP/RNBQKB1R b KQkq d3 0 3')
    - clone_color: Color of the clone's moves ('white' or 'black', 'w' or 'b').
    - clone_time: Remaining clock time for the clone in seconds.
    - weights_path: Path to the trained clone weights checkpoint (.pt file).
    - params: Optional dictionary of inference parameters:
        - elo: int = 1500 (Clone Elo rating)
        - maia_checkpoint: str = "./models/maia3-5m.pt"
        - opp_time: float = None (Opponent remaining clock seconds, defaults to clone_time)
        - opp_last_think: float = 0.0 (Opponent last move think time in seconds)
        - temperature: float = 1.0 (Move selection sampling temperature)

Returns:
    ReplayMoveResult: A tuple subclass (move_san, new_clock_time) supporting both:
        - Tuple unpacking: `move_san, new_clock = replay_clone_move(...)`
        - Named attributes: `res.move`, `res.new_clock_time`, `res.seconds_spent`
        - Dictionary conversion: `res.to_dict()`
"""

from __future__ import annotations

import math
import os
import random
import sys
from collections import deque
from pathlib import Path
from typing import Any, Optional

import chess
import torch

# Ensure ROOT and Model directories are in sys.path
ROOT = Path(__file__).resolve().parent.parent.parent
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

from Model.implementation import Clone, S
from Model.features import PIECE_TYPES, VALUES, compute_context_features, compute_move_features
from maia3.dataset import get_legal_moves_mask, tokenize_board
from maia3.uci import Maia3UCIEngine, parse_args

# Global model cache: {(weights_path, maia_checkpoint, device): (engine, clone)}
_MODEL_CACHE: dict[tuple[str, str, str], tuple[Maia3UCIEngine, Clone]] = {}


class ReplayMoveResult(tuple):
    """
    Subclass of tuple (move_san, new_clock_time) providing both tuple unpacking
    and named attribute/dict access for frontend JSON serialization.
    """

    def __new__(
        cls,
        move_san: str,
        new_clock_time: float,
        seconds_spent: float = 0.0,
        move_uci: str = "",
    ):
        return super().__new__(cls, (move_san, new_clock_time))

    def __init__(
        self,
        move_san: str,
        new_clock_time: float,
        seconds_spent: float = 0.0,
        move_uci: str = "",
    ):
        self.move = move_san
        self.move_san = move_san
        self.new_clock_time = float(new_clock_time)
        self.seconds_spent = float(seconds_spent)
        self.move_uci = move_uci

    def to_dict(self) -> dict[str, Any]:
        return {
            "move": self.move_san,
            "new_clock_time": self.new_clock_time,
            "seconds_spent": self.seconds_spent,
            "move_uci": self.move_uci,
        }

    def __repr__(self) -> str:
        return f"ReplayMoveResult(move='{self.move_san}', new_clock_time={self.new_clock_time}, seconds_spent={self.seconds_spent})"


def sample_move_index(scores_1d: torch.Tensor, temperature: float = 0.7, top_p: float = 0.85) -> int:
    """Samples a move slot index from 1-D scores using top-p nucleus sampling."""
    if temperature <= 0.0:
        return int(torch.argmax(scores_1d).item())

    scaled = scores_1d / max(temperature, 1e-4)
    probs = torch.softmax(scaled, dim=-1)

    if top_p < 1.0:
        sorted_probs, sorted_idx = torch.sort(probs, descending=True)
        cumulative = torch.cumsum(sorted_probs, dim=-1)
        keep = cumulative <= top_p
        keep[0] = True  # Always keep at least the #1 candidate move
        kept_probs = sorted_probs[keep]
        kept_idx = sorted_idx[keep]
        kept_probs = kept_probs / kept_probs.sum()
        choice = torch.multinomial(kept_probs, num_samples=1).item()
        return int(kept_idx[choice].item())

    return int(torch.multinomial(probs, num_samples=1).item())


def _get_or_load_models(
    weights_path: str | Path,
    maia_checkpoint: Optional[str | Path] = None,
    device: Optional[str] = None,
) -> tuple[Maia3UCIEngine, Clone]:
    """Loads and caches Maia-3 and Clone neural networks for sub-20ms inference."""
    weights_path = Path(weights_path).resolve()
    if not weights_path.is_file():
        raise FileNotFoundError(f"Clone weights file not found at: {weights_path}")

    if maia_checkpoint is None:
        maia_checkpoint = next(
            (p for p in [
                ROOT / "models" / "maia3-5m.pt",
                Path("./models/maia3-5m.pt"),
            ] if p.is_file()),
            Path("./models/maia3-5m.pt"),
        )
    maia_checkpoint = Path(maia_checkpoint).resolve()

    if device is None:
        device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")

    cache_key = (str(weights_path), str(maia_checkpoint), device)
    if cache_key in _MODEL_CACHE:
        return _MODEL_CACHE[cache_key]

    # 1. Initialize Maia-3 Engine
    uci_args = ["--model", "maia3-5m", "--use-uci-history", "--device", device]
    if maia_checkpoint.is_file():
        uci_args.extend(["--checkpoint", str(maia_checkpoint)])
    cfg = parse_args(uci_args)
    engine = Maia3UCIEngine(cfg)
    engine.ensure_model_loaded()

    # 2. Initialize Clone MLP Model
    clone = Clone()
    clone.load_state_dict(torch.load(weights_path, map_location="cpu", weights_only=True))
    clone.eval()

    _MODEL_CACHE[cache_key] = (engine, clone)
    return engine, clone


def replay_clone_move(
    fen: str,
    clone_color: str | chess.Color,
    clone_time: float,
    weights_path: str | Path,
    params: Optional[dict[str, Any]] = None,
    **kwargs,
) -> ReplayMoveResult:
    """
    Computes the clone's next move and remaining clock time from a FEN board state.

    Args:
        fen: Current board state in FEN notation (e.g. 'r1bqkbnr/pppp1ppp/2n5/4p3/3PP3/5N2/PPP2PPP/RNBQKB1R b KQkq d3 0 3').
        clone_color: Color of the clone ("white"/"black", "w"/"b", or chess.WHITE/chess.BLACK).
        clone_time: Current remaining clock time for the clone in seconds.
        weights_path: Path to clone weights checkpoint (e.g. "models/opponent.pt").
        params: Optional dictionary of inference parameters:
            - elo: Clone Elo rating (default: 1500)
            - maia_checkpoint: Path to Maia checkpoint (default: models/maia3-5m.pt)
            - opp_time: Opponent remaining clock time (default: clone_time)
            - opp_last_think: Opponent last move think seconds (default: 0.0)
            - temperature: Sampling temperature (default: 1.0)
        **kwargs: Overrides for any param key.

    Returns:
        ReplayMoveResult(move_san, new_clock_time)
        Unpackable as: `move, new_clock = replay_clone_move(...)`
    """
    merged_params = dict(params or {})
    merged_params.update(kwargs)

    # 1. Parse board state from FEN
    try:
        board = chess.Board(fen.strip())
    except Exception as e:
        raise ValueError(f"Invalid FEN string '{fen}': {e}") from e

    if board.is_game_over():
        raise ValueError(f"Game is already over in FEN: {fen}")

    # 2. Parse clone color
    if isinstance(clone_color, str):
        color_clean = clone_color.strip().lower()
        if color_clean in ("w", "white"):
            target_color = chess.WHITE
        elif color_clean in ("b", "black"):
            target_color = chess.BLACK
        else:
            raise ValueError(f"Invalid clone_color '{clone_color}'. Use 'white' or 'black'.")
    else:
        target_color = clone_color

    if board.turn != target_color:
        side_to_move = "White" if board.turn == chess.WHITE else "Black"
        clone_side = "White" if target_color == chess.WHITE else "Black"
        raise ValueError(f"It is {side_to_move}'s turn in FEN, but clone color was specified as {clone_side}.")

    # 3. Parse parameters
    elo = int(merged_params.get("elo", 1800))
    opp_elo = int(merged_params.get("opp_elo", elo))
    maia_ckpt = merged_params.get("maia_checkpoint")
    opp_time = float(merged_params.get("opp_time", clone_time))
    opp_last_think = float(merged_params.get("opp_last_think", 0.0))
    temperature = float(merged_params.get("temperature", 0.7))
    top_p = float(merged_params.get("top_p", 0.85))
    device = merged_params.get("device")

    # 4. Load models from cache
    engine, clone = _get_or_load_models(
        weights_path=weights_path,
        maia_checkpoint=maia_ckpt,
        device=device,
    )

    # 5. Compute Maia-3 legal moves and logits conditioned on both ratings
    engine.board = board.copy()
    tokens = engine._tokens_from_history(
        deque([tokenize_board(board)], maxlen=engine.cfg.history)
    ).unsqueeze(0).to(engine.cfg.device)

    elos = torch.tensor([elo], dtype=torch.long, device=engine.cfg.device)
    opp_elos = torch.tensor([opp_elo], dtype=torch.long, device=engine.cfg.device)
    with torch.no_grad():
        logits_move, _, _ = engine.model(tokens, elos, opp_elos)
    logits_full = logits_move[0].float().cpu()

    mask = get_legal_moves_mask(board, engine.all_moves_dict)
    moves, vals = [], []
    for idx in mask.nonzero(as_tuple=False).flatten().tolist():
        mv = engine._move_from_index(idx)
        if mv is not None:
            moves.append(mv)
            vals.append(logits_full[idx])

    if not moves:
        raise ValueError(f"No legal moves available for position: {fen}")

    # CRITICAL: Sort legal moves descending by Maia-3 logit
    # This precisely matches the training representation in Model/maia_extractor.py!
    sorted_pairs = sorted(zip(moves, vals), key=lambda pair: pair[1].item(), reverse=True)
    if len(sorted_pairs) > S:
        sorted_pairs = sorted_pairs[:S]

    moves = [p[0] for p in sorted_pairs]
    vals = torch.stack([p[1] for p in sorted_pairs])
    n = len(moves)

    # 6. Extract 28 features (16 move features + 12 context features)
    clocks = {
        board.turn: float(clone_time),
        not board.turn: float(opp_time),
    }
    avg_think = float(merged_params.get("avg_think", 0.0))
    ply = board.fullmove_number * 2 - (2 if board.turn == chess.WHITE else 1)

    # Softmax probabilities over legal moves
    maia_probs = torch.softmax(vals, dim=0)

    # 12 Context features
    context_feats = compute_context_features(
        board=board,
        own_clock=clocks[board.turn],
        opp_clock=clocks[not board.turn],
        ply=ply,
        opp_last_think_s=opp_last_think,
        avg_think_s=avg_think,
        num_legal_moves=n,
        probs_tensor=maia_probs,
    )

    # 16 Move features per legal move
    rows = []
    for slot_idx, m in enumerate(moves):
        logit_val = vals[slot_idx].item()
        prob_val = maia_probs[slot_idx].item()
        rank_val = slot_idx + 1  # 1-based rank (1 for top Maia move)
        log_rank_val = math.log(rank_val)

        move_feats = compute_move_features(
            board=board,
            move=m,
            maia_logit=logit_val,
            maia_prob=prob_val,
            maia_log_rank=log_rank_val,
        )
        rows.append(move_feats + context_feats)

    X = torch.zeros(1, S, 28)
    X[0, :n] = torch.tensor(rows, dtype=torch.float)
    packed = torch.zeros(1, S)
    packed[0, :n] = vals
    mask_tensor = torch.zeros(1, S)
    mask_tensor[0, :n] = 1.0

    # 7. Clone forward pass
    with torch.no_grad():
        offsets, time_out = clone(X)

    scores = (packed + offsets).masked_fill(mask_tensor == 0, float("-inf"))

    # 8. Move Selection via Top-P Nucleus Sampling
    slot = sample_move_index(scores[0, :n], temperature=temperature, top_p=top_p)

    chosen_move = moves[slot]
    move_san = board.san(chosen_move)
    move_uci = chosen_move.uci()

    # 9. Think-time computation and clock update
    mean = time_out[0, slot, 0].item()
    log_std = time_out[0, slot, 1].item()

    try:
        seconds = math.exp(mean + math.exp(log_std) * random.gauss(0, 1))
    except OverflowError:
        seconds = float(clone_time)

    if not math.isfinite(seconds):
        seconds = float(clone_time)

    seconds = min(max(seconds, 0.1), float(clone_time))
    new_clock_time = max(0.0, round(float(clone_time) - seconds, 2))

    return ReplayMoveResult(
        move_san=move_san,
        new_clock_time=new_clock_time,
        seconds_spent=round(seconds, 2),
        move_uci=move_uci,
    )


# Alias
replay_move = replay_clone_move

__all__ = [
    "replay_clone_move",
    "replay_move",
    "ReplayMoveResult",
]

