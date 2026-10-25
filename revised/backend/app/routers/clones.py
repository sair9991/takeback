from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from app.db.repositories import model_repo
from app.dependencies import get_optional_current_user
from app.schemas.clone import (
    CloneSearchResult,
    CloneStyleResponse,
    PredictStateRequest,
    PredictStateResponse,
)
from app.services import inference_service, commentary_service

router = APIRouter(tags=["Clones"])


@router.post("/api/predict-next-state", response_model=PredictStateResponse)
def predict_next_state(
    payload: PredictStateRequest,
    current_user: Optional[dict] = Depends(get_optional_current_user),
) -> PredictStateResponse:
    """Predict the opponent clone's next move and record model access audit."""
    user_id = (current_user.get("user_id") if current_user else None) or payload.user_id
    try:
        return inference_service.predict_clone_move(
            fen=payload.fen,
            opponent_color=payload.opponent_color,
            my_clock=payload.my_clock,
            opponent_clock=payload.opponent_clock,
            opponent_username=payload.opponent_username,
            opponent_elo=payload.opponent_elo,
            my_elo=payload.my_elo,
            accessed_by_user_id=user_id,
        )
    except (RuntimeError, FileNotFoundError) as e:
        raise HTTPException(status_code=503, detail=f"Model unavailable: {str(e)}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Inference error: {str(e)}")


@router.get("/api/clones")
def list_clones() -> list[dict[str, Any]]:
    """List all trained opponent models sorted by total access count."""
    return model_repo.list_models()


@router.get("/api/clones/search", response_model=List[CloneSearchResult])
def search_clones(
    q: str = Query(..., description="Natural language playing style query (e.g. 'aggressive attacker', 'fast blitzer')"),
    limit: int = Query(default=20, ge=1, le=100),
) -> List[CloneSearchResult]:
    """Search trained clones by playing style description using Gemma embeddings and text matching."""
    from app.services import embedding_service
    embedding = embedding_service.get_text_embedding(q)
    return model_repo.search_clones_by_style(q, query_embedding=embedding, limit=limit)


@router.get("/api/clones/{player_id}/stats")
def get_clone_stats(player_id: str) -> dict[str, Any]:
    """Retrieve usage stats, access counter, and timestamps for a specific model."""
    stats = model_repo.get_model_stats(player_id)
    if not stats:
        raise HTTPException(status_code=404, detail=f"Model for '{player_id}' not found")
    return stats


@router.get("/api/clones/{player_id}/style", response_model=CloneStyleResponse)
def get_clone_style(
    player_id: str,
    refresh: bool = Query(default=False, description="Force re-generation of playing style via Gemma"),
) -> CloneStyleResponse:
    """Retrieve a Gemma-powered natural language description of the clone's playing style and traits."""
    return commentary_service.describe_clone_style(player_id, refresh=refresh)


@router.get("/api/clones/{player_id}/logs")
def get_clone_logs(
    player_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Retrieve paginated audit logs of who accessed this clone and when."""
    return model_repo.get_model_access_logs(player_id, limit=limit, offset=offset)


@router.get("/api/users/{user_id}/models/stats")
def get_user_models_stats(user_id: str) -> dict[str, Any]:
    """Retrieve access count summary and logs for all models owned or created by a user."""
    return model_repo.get_user_models_stats(user_id)
