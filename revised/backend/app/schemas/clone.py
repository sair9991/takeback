from typing import List, Optional
from pydantic import BaseModel, Field


class PredictStateRequest(BaseModel):
    fen: str = Field(..., description="Current FEN string of the board")
    opponent_color: str = Field(..., description="'white' or 'black'")
    my_clock: float = Field(..., description="User's remaining clock in seconds")
    opponent_clock: float = Field(..., description="Opponent's remaining clock in seconds")
    opponent_username: Optional[str] = Field(default=None, description="Opponent's handle/ID")
    opponent_elo: Optional[int] = Field(default=None, description="Opponent Elo rating")
    my_elo: Optional[int] = Field(default=None, description="Player Elo rating")
    user_id: Optional[str] = Field(default=None, description="Requesting user ID or handle")


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


class CloneStyleResponse(BaseModel):
    player_id: str
    style_description: str
    traits: List[str] = []
    avg_think_time: Optional[float] = None
    total_moves_logged: Optional[int] = None
    cached: bool = False


class CloneSearchResult(BaseModel):
    player_id: str
    model_name: str = "clone"
    style_description: Optional[str] = None
    val_accuracy: Optional[float] = None
    access_count: int = 0
    similarity_score: Optional[float] = Field(default=None, description="Semantic match relevance score (0.0 to 1.0)")
