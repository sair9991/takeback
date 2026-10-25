import math
import random
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Any, Optional
import chess
import torch
from app.config import settings
from app.db.repositories import model_repo, game_repo
from app.schemas.clone import PredictStateResponse

# Ensure Model and maia3 are accessible in sys.path
for p in (str(settings.MODEL_CODE_DIR), str(settings.MAIA3_DIR), str(settings.PROJECT_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from app.ml.implementation import Clone, S
    from app.ml.features import compute_context_features, compute_move_features
    from maia3.dataset import get_legal_moves_mask, tokenize_board
    from maia3.uci import Maia3UCIEngine, parse_args
except Exception as e:
    print(f"[InferenceService Warning] Neural net packages unavailable: {e}")
    Clone = None
    S = 64

_MODEL_CACHE: dict[tuple[str, str, str], tuple[Any, Any]] = {}
_INFERENCE_LOCK = threading.Lock()


MAIA3_URL = "https://huggingface.co/UofTCSSLab/Maia3-5M/resolve/main/maia3-5m.pt"


def ensure_maia_checkpoint() -> Path:
    maia_ckpt = settings.MODELS_DIR / "maia3-5m.pt"
    if not maia_ckpt.is_file():
        import urllib.request
        maia_ckpt.parent.mkdir(parents=True, exist_ok=True)
        print(f"[Maia3] Downloading foundation model from {MAIA3_URL}...")
        urllib.request.urlretrieve(MAIA3_URL, maia_ckpt)
        print("[Maia3] Download complete!")
    return maia_ckpt


def sample_move_index(scores_1d: torch.Tensor, temperature: float = 0.7, top_p: float = 0.85) -> int:
    if temperature <= 0.0:
        return int(torch.argmax(scores_1d).item())

    scaled = scores_1d / max(temperature, 1e-4)
    probs = torch.softmax(scaled, dim=-1)

    if top_p < 1.0:
        sorted_probs, sorted_idx = torch.sort(probs, descending=True)
        cumulative = torch.cumsum(sorted_probs, dim=-1)
        keep = cumulative <= top_p
        keep[0] = True
        kept_probs = sorted_probs[keep]
        kept_idx = sorted_idx[keep]
        kept_probs = kept_probs / kept_probs.sum()
        choice = torch.multinomial(kept_probs, num_samples=1).item()
        return int(kept_idx[choice].item())

    return int(torch.multinomial(probs, num_samples=1).item())


def _load_models(weights_path: Path, maia_checkpoint: Path, device: str):
    cache_key = (str(weights_path), str(maia_checkpoint), device)
    if cache_key in _MODEL_CACHE:
        return _MODEL_CACHE[cache_key]

    uci_args = ["--model", "maia3-5m", "--use-uci-history", "--device", device]
    if maia_checkpoint.is_file():
        uci_args.extend(["--checkpoint", str(maia_checkpoint)])
    cfg = parse_args(uci_args)
    engine = Maia3UCIEngine(cfg)
    engine.ensure_model_loaded()

    clone = Clone()
    clone.load_state_dict(torch.load(weights_path, map_location="cpu", weights_only=True))
    clone.eval()

    _MODEL_CACHE[cache_key] = (engine, clone)
    return engine, clone


def predict_clone_move(
    fen: str,
    opponent_color: str,
    my_clock: float,
    opponent_clock: float,
    opponent_username: Optional[str] = None,
    opponent_elo: Optional[int] = None,
    my_elo: Optional[int] = None,
    accessed_by_user_id: Optional[str] = None,
) -> PredictStateResponse:
    board = chess.Board(fen)
    legal_moves = list(board.legal_moves)

    if not legal_moves or board.is_game_over():
        return PredictStateResponse(
            move="",
            san="",
            uci="",
            fen=fen,
            think_time=0.0,
            opponent_clock=opponent_clock,
            my_clock=my_clock,
            is_check=board.is_check(),
            is_game_over=True,
        )

    target_color = chess.WHITE if opponent_color.lower().startswith("w") else chess.BLACK
    weights_path = model_repo.get_model_weights_path(opponent_username or "")
    maia_ckpt = ensure_maia_checkpoint()

    chosen_move = None
    think_time = None

    # 1. Neural Net Inference via Maia-3 + Clone MLP
    if Clone and weights_path and weights_path.is_file() and board.turn == target_color:
        try:
            device = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
            with _INFERENCE_LOCK:
                engine, clone = _load_models(weights_path, maia_ckpt, device)
                engine.board = board.copy()
                tokens = engine._tokens_from_history(
                    deque([tokenize_board(board)], maxlen=engine.cfg.history)
                ).unsqueeze(0).to(engine.cfg.device)

                clone_elo = int(opponent_elo or 1800)
                user_elo = int(my_elo or 1800)
                elos = torch.tensor([clone_elo], dtype=torch.long, device=engine.cfg.device)
                opp_elos = torch.tensor([user_elo], dtype=torch.long, device=engine.cfg.device)

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

                if moves:
                    sorted_pairs = sorted(zip(moves, vals), key=lambda pair: pair[1].item(), reverse=True)[:S]
                    moves = [p[0] for p in sorted_pairs]
                    vals = torch.stack([p[1] for p in sorted_pairs])
                    n = len(moves)

                    maia_probs = torch.softmax(vals, dim=0)
                    ply = board.fullmove_number * 2 - (2 if board.turn == chess.WHITE else 1)
                    context_feats = compute_context_features(
                        board=board,
                        own_clock=float(opponent_clock),
                        opp_clock=float(my_clock),
                        ply=ply,
                        opp_last_think_s=0.0,
                        avg_think_s=0.0,
                        num_legal_moves=n,
                        probs_tensor=maia_probs,
                    )

                    rows = []
                    for slot_idx, m in enumerate(moves):
                        rows.append(
                            compute_move_features(
                                board=board,
                                move=m,
                                maia_logit=vals[slot_idx].item(),
                                maia_prob=maia_probs[slot_idx].item(),
                                maia_log_rank=math.log(slot_idx + 1),
                            )
                            + context_feats
                        )

                    X = torch.zeros(1, S, 28)
                    X[0, :n] = torch.tensor(rows, dtype=torch.float)
                    packed = torch.zeros(1, S)
                    packed[0, :n] = vals
                    mask_tensor = torch.zeros(1, S)
                    mask_tensor[0, :n] = 1.0

                    with torch.no_grad():
                        offsets, time_out = clone(X)

                    scores = (packed + offsets).masked_fill(mask_tensor == 0, float("-inf"))
                    slot = sample_move_index(scores[0, :n], temperature=0.7, top_p=0.85)
                    chosen_move = moves[slot]

                    mean = time_out[0, slot, 0].item()
                    log_std = time_out[0, slot, 1].item()
                    sec = math.exp(mean + math.exp(log_std) * random.gauss(0, 1))
                    think_time = round(max(0.4, min(sec, float(opponent_clock))), 1)
        except Exception as e:
            print(f"[Inference Error] Neural net forward pass failed: {e}")

    # 2. Heuristic fallback if neural net is unavailable
    if not chosen_move:
        captures = [m for m in legal_moves if board.is_capture(m)]
        checks = [m for m in legal_moves if board.gives_check(m)]
        if checks and random.random() < 0.55:
            chosen_move = random.choice(checks)
        elif captures and random.random() < 0.65:
            chosen_move = random.choice(captures)
        else:
            chosen_move = random.choice(legal_moves)

    if think_time is None:
        think_time = round(random.uniform(1.2, 3.5), 1)

    new_opp_clock = max(0.0, round(opponent_clock - think_time, 1))
    san_move = board.san(chosen_move)
    uci_move = chosen_move.uci()
    board.push(chosen_move)

    if opponent_username:
        try:
            model_repo.record_model_access(
                opponent_username,
                accessed_by_user_id=accessed_by_user_id,
                think_time=think_time,
            )
        except Exception:
            pass

    return PredictStateResponse(
        move=san_move,
        san=san_move,
        uci=uci_move,
        fen=board.fen(),
        think_time=think_time,
        opponent_clock=new_opp_clock,
        my_clock=my_clock,
        is_check=board.is_check(),
        is_game_over=board.is_game_over(),
    )
