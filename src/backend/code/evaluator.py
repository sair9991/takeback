import json
import os
import shutil
import helper

try:
    import chess
    import chess.engine
except ImportError:
    raise ImportError("python-chess is required. Please install it via 'pip install python-chess'.")

STOCKFISH_CANDIDATES = [
    "/opt/homebrew/bin/stockfish",
    "/usr/local/bin/stockfish",
    "/usr/bin/stockfish",
]


def find_stockfish() -> str:
    path = shutil.which("stockfish")
    if path:
        return path
    for candidate in STOCKFISH_CANDIDATES:
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError("Stockfish binary not found. Please install Stockfish via 'brew install stockfish'.")


def cp_to_odds(cp: float) -> float:
    """Convert centipawn advantage to win percentage (0 to 100)."""
    clamped_cp = max(-1500, min(1500, cp))
    return round(100.0 / (1.0 + 10.0 ** (-clamped_cp / 400.0)), 1)


def evaluate_game(moves: list[dict], player_color: str = "white") -> list[float]:
    """
    Evaluate every ply strictly using Stockfish.
    Throws an error if Stockfish is not available.
    """
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


def get_cached_odds(game_id: str) -> list[float] | None:
    """Return cached odds from analyzed_games table if present."""
    row = helper.query_one(
        """
        SELECT odds FROM analyzed_games 
        WHERE (game_id = ? OR game_id = (SELECT game_id FROM games WHERE id = ?))
          AND odds IS NOT NULL AND odds != ''
        LIMIT 1
        """,
        (game_id, game_id),
    )
    if row and row.get("odds"):
        try:
            return json.loads(row["odds"])
        except Exception:
            return None
    return None


def cache_game_odds(game_id: str, username: str = None) -> list[float]:
    """Fetch cached odds from database, or compute once with Stockfish and store."""
    cached = get_cached_odds(game_id)
    if cached is not None:
        return cached

    game = helper.query_one("SELECT * FROM games WHERE game_id = ? OR id = ?", (game_id, game_id))
    if not game:
        return []

    actual_gid = game.get("game_id") or str(game.get("id"))
    uid = username or game.get("player_id") or "stuffyness"

    moves = helper.query(
        "SELECT ply, side, move, time_remaining, clock_str FROM moves WHERE game_id = ? ORDER BY ply ASC",
        (actual_gid,),
    )
    if not moves:
        return []

    odds = evaluate_game(moves, game.get("player_color") or "white")
    odds_json = json.dumps(odds)

    helper.execute(
        """
        INSERT INTO analyzed_games (user_id, game_id, odds)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, game_id) DO UPDATE SET odds = excluded.odds
        """,
        (uid, actual_gid, odds_json),
    )
    if game_id != actual_gid:
        helper.execute(
            """
            INSERT INTO analyzed_games (user_id, game_id, odds)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, game_id) DO UPDATE SET odds = excluded.odds
            """,
            (uid, game_id, odds_json),
        )
    return odds

