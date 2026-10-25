from typing import List, Optional
from pydantic import BaseModel, Field
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


class SemanticSearchGameResponse(GameSummary):
    narrative: Optional[str] = None
    tags: List[str] = []
    similarity_score: float = Field(default=0.0, description="Cosine similarity score (0.0 to 1.0)")
