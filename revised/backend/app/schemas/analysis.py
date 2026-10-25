from typing import List, Optional
from pydantic import BaseModel
from app.schemas.game import GameSummary


class AnalyzeResponse(BaseModel):
    cached: bool
    status: str
    opponent: str
    job_id: Optional[str] = None
    stream_url: Optional[str] = None


class SearchGameResponse(GameSummary):
    narrative: Optional[str] = None
    tags: List[str] = []
