from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from app.db.repositories import model_repo
from app.dependencies import get_optional_current_user
from app.schemas.auth import UserResponse
from app.schemas.clone import PredictStateRequest, PredictStateResponse
from app.services import inference_service

router = APIRouter(tags=["Clones"])


@router.post("/api/predict-next-state", response_model=PredictStateResponse)
def predict_next_state(
    payload: PredictStateRequest,
    current_user: Optional[UserResponse] = Depends(get_optional_current_user),
) -> PredictStateResponse:
    """Predict the opponent clone's next move and record model access audit."""
    user_id = (current_user.user_id if current_user else None) or payload.user_id
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
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/clones")
def list_clones() -> list[dict[str, Any]]:
    """List all trained opponent models sorted by total access count."""
    return model_repo.list_models()


@router.get("/api/clones/{player_id}/stats")
def get_clone_stats(player_id: str) -> dict[str, Any]:
    """Retrieve usage stats, access counter, and timestamps for a specific model."""
    stats = model_repo.get_model_stats(player_id)
    if not stats:
        raise HTTPException(status_code=404, detail=f"Model for '{player_id}' not found")
    return stats


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
