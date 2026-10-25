import json
import os
import shutil
from typing import List, Optional
from app.config import settings
from app.db.repositories import analysis_repo, game_repo

try:
    import chess
    import chess.engine
except ImportError:
    chess = None

STOCKFISH_CANDIDATES = [
    "/usr/games/stockfish",
    "/usr/bin/stockfish",
    "/usr/local/bin/stockfish",
    "/opt/homebrew/bin/stockfish",
]


def find_stockfish() -> str:
    if settings.STOCKFISH_PATH and os.path.exists(settings.STOCKFISH_PATH):
        return settings.STOCKFISH_PATH
    path = shutil.which("stockfish")
    if path:
        return path
    for candidate in STOCKFISH_CANDIDATES:
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError("Stockfish binary not found. Please install Stockfish via 'apt install stockfish' or 'brew install stockfish'.")


def cp_to_odds(cp: float) -> float:
    """Convert centipawn advantage to win percentage (0.0 to 100.0)."""
    clamped_cp = max(-1500, min(1500, cp))
    return round(100.0 / (1.0 + 10.0 ** (-clamped_cp / 400.0)), 1)


def evaluate_game(moves: List[dict], player_color: str = "white") -> List[float]:
    stockfish_bin = find_stockfish()
    board = chess.Board()
    odds = []
    is_player_white = player_color.lower() == "white"

    with chess.engine.SimpleEngine.popen_uci(stockfish_bin) as engine:
        for m in moves:
            board.push_san(m["move"])
            info = engine.analyse(board, chess.engine.Limit(depth=10))
            score = info["score"].white()
            cp = (10000 if score.mate() > 0 else -10000) if score.is_mate() else (score.score() or 0)
            white_odds = cp_to_odds(cp)
            odds.append(white_odds if is_player_white else round(100.0 - white_odds, 1))

    return odds


def get_or_calculate_odds(game_id: str, username: Optional[str] = None) -> List[float]:
    # Check if already cached
    cached = analysis_repo.get_analysis_by_game(game_id, username)
    if cached and cached.get("odds"):
        val = cached["odds"]
        if isinstance(val, list):
            return val
        if isinstance(val, str):
            try:
                return json.loads(val)
            except Exception:
                pass

    game = game_repo.get_game_by_id(game_id)
    if not game:
        return []

    actual_gid = game.get("game_id") or str(game.get("id"))
    uid = username or game.get("player_id") or "guest"
    moves = game_repo.get_game_moves(actual_gid)
    if not moves:
        return []

    odds = evaluate_game(moves, game.get("player_color") or "white")
    analysis_repo.save_odds(uid, actual_gid, odds)
    return odds
