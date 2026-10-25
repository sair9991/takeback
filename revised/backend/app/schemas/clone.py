from typing import Optional
from pydantic import BaseModel, Field


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
