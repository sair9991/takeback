from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from app.db.repositories import game_repo, analysis_repo, user_repo
from app.schemas.game import GameSummary
from app.schemas.analysis import (
    AnalyzeResponse,
    SearchGameResponse,
    SemanticSearchGameResponse,
)
from app.services import evaluation_service, commentary_service, embedding_service
from app.workers import queue_manager

router = APIRouter(tags=["Analysis"])


def _resolve_user(identifier: str) -> tuple[str, str]:
    """Resolve identifier (user_id, email, or chess_com_username) -> (user_id, chess_com_username)."""
    target = (
        user_repo.get_user_by_id(identifier)
        or user_repo.get_user_by_email(identifier)
        or user_repo.get_user_by_chess_handle(identifier)
    )
    if target:
        return target["user_id"], target.get("chess_com_username") or identifier

    user_id = user_repo.ensure_user_exists(identifier, identifier)
    return user_id, identifier


@router.get("/api/users/{username}/games", response_model=List[GameSummary])
def get_user_games(
    username: str,
    limit: int = 50,
    offset: int = 0,
    sync: bool = False,
):
    owner_id, chess_handle = _resolve_user(username)

    games = game_repo.get_user_games(owner_id, limit, offset)
    if not games and chess_handle != owner_id:
        games = game_repo.get_user_games(chess_handle, limit, offset)

    # If no games exist yet or sync requested, sync real games from Chess.com API
    if not games or sync:
        synced = game_repo.sync_user_games_from_chess_com(chess_handle, user_id=owner_id, limit=limit)
        if synced:
            return synced

    return games


@router.get("/api/users/{username}/analyzed-games", response_model=List[GameSummary])
def get_analyzed_games(username: str, limit: int = 50, offset: int = 0):
    user_id, _ = _resolve_user(username)
    return analysis_repo.get_user_analyzed_games(user_id, limit, offset)


@router.post("/api/users/{username}/analyze/{game_id}", response_model=AnalyzeResponse)
def analyze_game(
    username: str,
    game_id: str,
    background_tasks: BackgroundTasks,
    opponent: Optional[str] = None,
):
    user_id, _ = _resolve_user(username)
    game = game_repo.get_game_by_id(game_id)
    opp = (game.get("opponent_username") if game else None) or opponent or "Opponent"

    if queue_manager.is_cached(opp):
        background_tasks.add_task(evaluation_service.get_or_calculate_odds, game_id, user_id)
        commentary_service.start_background_commentary_generation(game_id, user_id)
        return AnalyzeResponse(cached=True, status="ready", opponent=opp)

    job_id = queue_manager.enqueue(opp, user_id, game_id)
    return AnalyzeResponse(
        cached=False,
        status="queued",
        job_id=job_id,
        opponent=opp,
        stream_url=f"/api/analysis/stream/{job_id}",
    )


@router.get("/api/users/{username}/search-games", response_model=List[SearchGameResponse])
def search_games(username: str, q: str):
    """Keyword search across game narratives, opponent, result, and tags."""
    user_id, _ = _resolve_user(username)
    return analysis_repo.search_analyzed_games(user_id, q)


@router.get("/api/users/{username}/search-semantic", response_model=List[SemanticSearchGameResponse])
def search_semantic(
    username: str,
    q: str,
    limit: int = Query(default=20, ge=1, le=100),
):
    """Natural language semantic vector search powered by local Gemma embeddings with hybrid keyword fallback."""
    user_id, chess_handle = _resolve_user(username)
    embedding = None
    try:
        embedding = embedding_service.get_text_embedding(q)
    except Exception:
        pass

    results = []
    if embedding:
        try:
            results = analysis_repo.search_semantic_games(user_id, embedding, limit=limit)
        except Exception:
            pass

    # If vector search returned nothing or embedding service is offline, fallback to text/tag matching
    if not results:
        keyword_matches = analysis_repo.search_analyzed_games(user_id, q)
        if not keyword_matches and chess_handle != user_id:
            keyword_matches = analysis_repo.search_analyzed_games(chess_handle, q)

        results = [
            SemanticSearchGameResponse(
                **r,
                similarity_score=0.80,
            )
            for r in keyword_matches[:limit]
        ]

    return results
