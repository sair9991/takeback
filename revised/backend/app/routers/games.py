from typing import List, Optional
import json
from fastapi import APIRouter, HTTPException, Query, Response, BackgroundTasks
from app.db.repositories import game_repo, analysis_repo
from app.schemas.game import GameSummary, GameDetailResponse, MoveRecord
from app.schemas.analysis import SemanticSearchGameResponse
from app.services import thumbnail_service, evaluation_service, commentary_service

router = APIRouter(prefix="/api/games", tags=["Games"])


@router.get("/user/{username}", response_model=List[GameSummary])
def get_user_games(username: str, limit: int = 50, offset: int = 0):
    return game_repo.get_user_games(username, limit, offset)


@router.get("/{game_id}", response_model=GameDetailResponse)
def get_game_detail(game_id: str, background_tasks: BackgroundTasks):
    """Fetch game metadata along with its chronological moves, cached odds, and commentary."""
    game = game_repo.get_game_by_id(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    actual_gid = game.get("game_id") or str(game.get("id"))
    moves_data = game_repo.get_game_moves(actual_gid)

    # Fetch cached odds or calculate once
    odds = []
    eval_error = None
    try:
        odds = evaluation_service.get_or_calculate_odds(actual_gid, game.get("player_id"))
    except Exception as e:
        eval_error = str(e)

    # Check if analysis is already cached in database
    cached_analysis = analysis_repo.get_analysis_by_game(actual_gid, game.get("player_id"))
    commentary = []
    narrative = ""
    tags = []
    has_valid_commentary = False
    gemma_error = None

    if cached_analysis and (cached_analysis.get("commentary") or cached_analysis.get("narrative")):
        narrative_text = cached_analysis.get("narrative") or ""
        is_bland = any(p in narrative_text.lower() for p in ["10-minute game between", "10-minute rapid game played by"])
        c = cached_analysis.get("commentary") or []
        parsed_c = c if isinstance(c, list) else (json.loads(c) if isinstance(c, str) else [])
        if not is_bland:
            commentary = parsed_c
            narrative = narrative_text
            tags = cached_analysis.get("narrative_tags") or []
            has_valid_commentary = True

    is_generating = commentary_service.is_generation_in_progress(actual_gid)
    if not has_valid_commentary:
        if not is_generating:
            is_generating = True
            commentary_service.start_background_commentary_generation(actual_gid, game.get("player_id"))
        else:
            is_generating = True

    formatted = game_repo.format_game_row(game)
    return GameDetailResponse(
        **formatted,
        moves=[MoveRecord(**m) for m in moves_data],
        odds=odds,
        commentary=commentary,
        narrative=narrative,
        tags=tags,
        is_generating=is_generating,
        error=gemma_error or eval_error,
    )


@router.get("/{game_id}/moves", response_model=List[MoveRecord])
def get_game_moves(game_id: str):
    rows = game_repo.get_game_moves(game_id)
    return [MoveRecord(**r) for r in rows]


@router.get("/{game_id}/thumbnail.svg")
@router.get("/{game_id}/thumbnail")
def get_game_thumbnail(game_id: str, ply: Optional[int] = None):
    game = game_repo.get_game_by_id(game_id)
    actual_gid = (game.get("game_id") if game else None) or game_id
    moves = [m["move"] for m in game_repo.get_game_moves(actual_gid)]
    player_color = (game.get("player_color") if game else "white") or "white"

    svg_data = thumbnail_service.get_thumbnail_svg(actual_gid, moves, player_color, ply)
    return Response(
        content=svg_data,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=604800"},
    )


@router.get("/{game_id}/similar", response_model=List[SemanticSearchGameResponse])
def get_similar_games(
    game_id: str,
    limit: int = Query(default=10, ge=1, le=50),
):
    """Find other analyzed games with similar tactical motifs and narrative themes."""
    return analysis_repo.find_similar_games(game_id, limit=limit)
