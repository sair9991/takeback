import math
import random
import time
from collections import deque
from pathlib import Path

import chess
import torch

from implementation import Clone, S
from maia3.dataset import get_legal_moves_mask, tokenize_board
from maia3.uci import Maia3UCIEngine, parse_args

# 16 move features, then 12 context features, padded to S slots like training.
PIECE_TYPES = [chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN, chess.KING]
VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}

cfg = parse_args(["--model", "maia3-5m", "--use-uci-history"])
engine = Maia3UCIEngine(cfg)
clone = Clone()
clone.load_state_dict(torch.load(Path(__file__).with_name("clone.pt"), map_location="cpu", weights_only=True))
clone.eval()

def ask_color():
    while True:
        choice = input("Your color (white/black): ").strip().lower()
        if choice in ("w", "white"):
            return chess.WHITE
        if choice in ("b", "black"):
            return chess.BLACK
        print("Enter white or black.")

def ask_elo():
    print("Elo examples: 1000, 1500, 2000. Any integer from 0 to 5000 works, such as 1642.")
    while True:
        raw = input("Your Elo: ").strip()
        try:
            elo = int(raw)
        except ValueError:
            print("Enter a whole number.")
            continue
        if 0 <= elo <= 5000:
            return elo
        print("Elo must be from 0 to 5000.")

def show_board(board):
    print(board)
    print()

def sync_engine(board, elo):
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

def maia_legal(board, elo):
    sync_engine(board, elo)
    engine.ensure_model_loaded()
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
    if len(moves) > S:
        top = torch.topk(torch.stack(vals), S).indices.tolist()
        moves = [moves[i] for i in top]
        vals = [vals[i] for i in top]
    return moves, torch.stack(vals)

def features(board, moves, logits, clocks, opp_last, avg_think):
    n = len(moves)
    probs = torch.softmax(logits, dim=0)
    order = torch.argsort(logits, descending=True)
    rank = torch.empty(n)
    rank[order] = torch.arange(1, n + 1, dtype=torch.float)
    entropy = -(probs * torch.log(probs.clamp(min=1e-8))).sum().item()
    own = clocks[board.turn] / 600
    opp = clocks[not board.turn] / 600
    ply = board.fullmove_number * 2 - (2 if board.turn == chess.WHITE else 1)
    mat = 0
    for piece in board.piece_map().values():
        v = VALUES.get(piece.piece_type, 0)
        mat += v if piece.color == board.turn else -v
    context = [
        own, opp, ply / 100, float(board.is_check()), n / S,
        math.log1p(opp_last), entropy / math.log(max(n, 2)), probs.max().item(),
        mat / 10, math.log1p(avg_think), (1 - own) - min(1.0, ply / 40), min(own, opp),
    ]
    rows = []
    for i, mv in enumerate(moves):
        piece = board.piece_at(mv.from_square)
        frm, to = chess.square_rank(mv.from_square), chess.square_rank(mv.to_square)
        forward = to > frm if board.turn == chess.WHITE else to < frm
        after = board.copy(stack=False)
        after.push(mv)
        hung = after.is_attacked_by(after.turn, mv.to_square) and not after.is_attacked_by(not after.turn, mv.to_square)
        one_hot = [1.0 if piece and piece.piece_type == kind else 0.0 for kind in PIECE_TYPES]
        rows.append([
            logits[i].item(), probs[i].item(), math.log(rank[i].item()),
            float(board.is_capture(mv)), float(board.gives_check(mv)),
            float(board.is_castling(mv)), float(mv.promotion is not None),
            *one_hot, float(not forward and frm != to), float(forward), float(hung),
            *context,
        ])
    X = torch.zeros(1, S, 28)
    X[0, :n] = torch.tensor(rows, dtype=torch.float)
    packed = torch.zeros(1, S)
    packed[0, :n] = logits
    mask = torch.zeros(1, S)
    mask[0, :n] = 1
    return X, packed, mask

def think_seconds(mean, log_std, clock):
    try:
        seconds = math.exp(mean + math.exp(log_std) * random.gauss(0, 1))
    except OverflowError:
        seconds = clock
    if not math.isfinite(seconds):
        seconds = clock
    return min(max(seconds, 0.1), clock)

def clone_move(board, elo, clocks, opp_last, think_times):
    moves, logits = maia_legal(board, elo)
    avg = sum(think_times) / len(think_times) if think_times else 0.0
    X, packed, mask = features(board, moves, logits, clocks, opp_last, avg)
    with torch.no_grad():
        offsets, time_out = clone(X)
    scores = (packed + offsets).masked_fill(mask == 0, float("-inf"))
    n = len(moves)
    slot = torch.multinomial(torch.softmax(scores[0, :n], dim=0), 1).item()
    mean = time_out[0, slot, 0].item()
    log_std = time_out[0, slot, 1].item()
    seconds = think_seconds(mean, log_std, clocks[board.turn])
    print(f"Clone thinks {seconds:.1f}s")
    time.sleep(seconds)
    clocks[board.turn] = max(0.0, clocks[board.turn] - seconds)
    think_times.append(seconds)
    san = board.san(moves[slot])
    board.push(moves[slot])
    print(f"Clone plays {san}")
    show_board(board)

user_color = ask_color()
elo = ask_elo()
board = chess.Board()
clocks = {chess.WHITE: 600.0, chess.BLACK: 600.0}
think_times, opp_last = [], 0.0
show_board(board)

if user_color == chess.BLACK and not board.is_game_over():
    clone_move(board, elo, clocks, opp_last, think_times)

while not board.is_game_over():
    started = time.time()
    raw = input("Your move (or quit): ").strip()
    opp_last = time.time() - started
    if raw.lower() in ("quit", "q", "exit"):
        break
    try:
        board.push_san(raw)
    except ValueError:
        print("Illegal move. Use chess notation such as e4, Nf3, or O-O.")
        continue

    if board.is_game_over():
        show_board(board)
        print(f"Game over: {board.result()}")
        break

    clone_move(board, elo, clocks, opp_last, think_times)
    if board.is_game_over():
        print(f"Game over: {board.result()}")
