import math
import random
from typing import Optional
from pydantic import BaseModel, Field


class PredictStateRequest(BaseModel):
    fen: str = Field(..., description="Current FEN string of the board")
    opponent_color: str = Field(..., description="'white' or 'black'")
    my_clock: float = Field(..., description="User's remaining clock in seconds")
    opponent_clock: float = Field(..., description="Opponent's remaining clock in seconds")
    opponent_username: Optional[str] = Field(default=None, description="Opponent's handle/ID")


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

    # 1. Try to use trained Clone model from Model/service.py if available
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
