from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks
from app.db.repositories import game_repo, analysis_repo
from app.schemas.game import GameSummary
from app.schemas.analysis import AnalyzeResponse, SearchGameResponse
from app.services import evaluation_service, commentary_service
from app.workers import queue_manager

router = APIRouter(tags=["Analysis"])


@router.get("/api/users/{username}/games", response_model=List[GameSummary])
def get_user_games_legacy(username: str, limit: int = 50, offset: int = 0):
    return game_repo.get_user_games(username, limit, offset)


@router.get("/api/users/{username}/analyzed-games", response_model=List[GameSummary])
def get_analyzed_games(username: str, limit: int = 50, offset: int = 0):
    return analysis_repo.get_user_analyzed_games(username, limit, offset)


@router.post("/api/users/{username}/analyze/{game_id}", response_model=AnalyzeResponse)
def analyze_game(
    username: str,
    game_id: str,
    background_tasks: BackgroundTasks,
    opponent: Optional[str] = None,
):
    game = game_repo.get_game_by_id(game_id)
    opp = (game.get("opponent_username") if game else None) or opponent or "Opponent"

    if queue_manager.is_cached(opp):
        background_tasks.add_task(evaluation_service.get_or_calculate_odds, game_id, username)
        background_tasks.add_task(commentary_service.get_or_generate_commentary, game_id, username)
        return AnalyzeResponse(cached=True, status="ready", opponent=opp)

    job_id = queue_manager.enqueue(opp, username, game_id)
    return AnalyzeResponse(
        cached=False,
        status="queued",
        job_id=job_id,
        opponent=opp,
        stream_url=f"/api/analysis/stream/{job_id}",
    )


@router.get("/api/users/{username}/search-games", response_model=List[SearchGameResponse])
def search_games(username: str, q: str):
    return analysis_repo.search_analyzed_games(username, q)
