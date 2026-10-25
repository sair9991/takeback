import math
import os
import random
import sys
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

# Ensure project root and backend are in sys.path
ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = ROOT / "src" / "backend"
for p in (str(ROOT), str(BACKEND_DIR), str(ROOT / "Model"), str(ROOT / "maia3")):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from replay_service import replay_clone_move
except Exception:
    replay_clone_move = None


class PredictStateRequest(BaseModel):
    fen: str = Field(..., description="Current FEN string of the board")
    opponent_color: str = Field(..., description="'white' or 'black'")
    my_clock: float = Field(..., description="User's remaining clock in seconds")
    opponent_clock: float = Field(..., description="Opponent's remaining clock in seconds")
    opponent_username: Optional[str] = Field(default=None, description="Opponent's handle/ID")
    opponent_elo: Optional[int] = Field(default=None, description="Opponent Elo rating")
    my_elo: Optional[int] = Field(default=None, description="Player Elo rating")


class PredictStateResponse(BaseModel):
    move: str
    san: str
    uci: str
    fen: str
    think_time: float
    opponent_clock: float
    my_clock: float
    is_check: bool
    is_game_over: bool


def predict_clone_move(
    fen: str,
    opponent_color: str,
    my_clock: float,
    opponent_clock: float,
    opponent_username: Optional[str] = None,
    opponent_elo: Optional[int] = None,
    my_elo: Optional[int] = None,
) -> dict:
    """
    Predicts the opponent clone's next move and think time.
    Returns the new board state (FEN) and updated clocks.
    """
    import chess

    board = chess.Board(fen)
    legal_moves = list(board.legal_moves)

    if not legal_moves:
        return {
            "move": "",
            "san": "",
            "uci": "",
            "fen": fen,
            "think_time": 0.0,
            "opponent_clock": opponent_clock,
            "my_clock": my_clock,
            "is_check": board.is_check(),
            "is_game_over": True,
        }

    chosen_move = None
    think_time = None

    # 1. Try real replay_service neural inference if weights exist
    opp_key = (opponent_username or "").lower().strip()
    weights_path = None
    try:
        import helper
        model_row = helper.query_one("SELECT weights_path FROM models WHERE LOWER(player_id) = ?", (opp_key,))
        if model_row and model_row.get("weights_path"):
            w_candidate = Path(model_row["weights_path"])
            if not w_candidate.is_absolute():
                w_candidate = ROOT / w_candidate
            if w_candidate.is_file():
                weights_path = w_candidate

        if not weights_path:
            # Fall back to the most recently trained opponent clone in the database
            latest = helper.query_one("SELECT weights_path FROM models ORDER BY updated_at DESC, created_at DESC LIMIT 1")
            if latest and latest.get("weights_path"):
                w_candidate = Path(latest["weights_path"])
                if not w_candidate.is_absolute():
                    w_candidate = ROOT / w_candidate
                if w_candidate.is_file():
                    weights_path = w_candidate
    except Exception:
        pass

    # Look up Elo ratings from database if not explicitly passed
    if (not opponent_elo or not my_elo) and opp_key:
        try:
            import helper
            r = helper.query_one(
                "SELECT opponent_elo, player_elo FROM games WHERE LOWER(opponent_username) = ? LIMIT 1",
                (opp_key,),
            )
            if r:
                opponent_elo = opponent_elo or r.get("opponent_elo")
                my_elo = my_elo or r.get("player_elo")
        except Exception:
            pass

    clone_elo = int(opponent_elo or 1800)
    user_elo = int(my_elo or 1800)

    if replay_clone_move and weights_path and weights_path.is_file():
        try:
            res = replay_clone_move(
                fen=fen,
                clone_color=opponent_color,
                clone_time=opponent_clock,
                weights_path=weights_path,
                params={
                    "elo": clone_elo,
                    "opp_elo": user_elo,
                    "opp_time": my_clock,
                    "temperature": 0.7,
                    "top_p": 0.85,
                },
            )
            move_obj = board.parse_san(res.move)
            san_move = res.move
            uci_move = res.move_uci or move_obj.uci()
            think_time = round(res.seconds_spent, 1)
            new_opp_clock = round(res.new_clock_time, 1)
            board.push(move_obj)
            return {
                "move": san_move,
                "san": san_move,
                "uci": uci_move,
                "fen": board.fen(),
                "think_time": think_time,
                "opponent_clock": new_opp_clock,
                "my_clock": my_clock,
                "is_check": board.is_check(),
                "is_game_over": board.is_game_over(),
            }
        except Exception as e:
            print(f"[Clone Inference] replay_clone_move fallback: {e}")

    # 2. Try to use trained Clone model from Model/service.py if available
    try:
        from Model.service import predict_move
        res = predict_move(
            board=board,
            own_clock=opponent_clock,
            opp_clock=my_clock,
        )
        if res.get("chosen_san"):
            chosen_move = board.parse_san(res["chosen_san"])
            think_time = res.get("think_seconds")
    except Exception:
        pass

    # 2. Intelligent fallback selection if weights/model are not in memory
    if not chosen_move:
        captures = [m for m in legal_moves if board.is_capture(m)]
        checks = [m for m in legal_moves if board.gives_check(m)]

        if checks and random.random() < 0.55:
            chosen_move = random.choice(checks)
        elif captures and random.random() < 0.65:
            chosen_move = random.choice(captures)
        else:
            chosen_move = random.choice(legal_moves)

    # 3. Predict realistic human think time (log-normal distribution)
    if think_time is None:
        if opponent_clock < 20:
            base_time = random.uniform(0.8, 2.0)
        elif opponent_clock < 60:
            base_time = random.uniform(1.5, 4.0)
        else:
            base_time = random.lognormvariate(1.2, 0.4)
        think_time = round(max(0.6, min(base_time, max(1.0, opponent_clock * 0.25))), 1)

    new_opp_clock = max(0.0, round(opponent_clock - think_time, 1))

    san_move = board.san(chosen_move)
    uci_move = chosen_move.uci()
    board.push(chosen_move)
    new_fen = board.fen()

    return {
        "move": san_move,
        "san": san_move,
        "uci": uci_move,
        "fen": new_fen,
        "think_time": think_time,
        "opponent_clock": new_opp_clock,
        "my_clock": my_clock,
        "is_check": board.is_check(),
        "is_game_over": board.is_game_over(),
    }
