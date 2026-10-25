from typing import List, Optional
from pydantic import BaseModel


class GameSummary(BaseModel):
    id: str
    player_id: str
    opponent: str
    date: str
    platform: str
    initials: str
    result: Optional[str] = None
    time_control: Optional[str] = None
    player_color: Optional[str] = None
    player_elo: Optional[int] = None
    opponent_elo: Optional[int] = None
    thumbnailUrl: str


class MoveRecord(BaseModel):
    ply: int
    side: str
    move: str
    time_remaining: Optional[float] = None
    clock_str: Optional[str] = None


class GameDetailResponse(GameSummary):
    moves: List[MoveRecord] = []
    odds: List[float] = []
    commentary: List[dict] = []
    narrative: str = ""
    tags: List[str] = []
    is_generating: bool = False
    error: Optional[str] = None
