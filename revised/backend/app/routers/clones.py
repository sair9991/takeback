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


@router.post("/api/clones/{player_id}/train")
@router.post("/api/train/{player_id}")
def train_clone_endpoint(
    player_id: str,
    force: bool = Query(default=False, description="Force retraining even if model already exists"),
    current_user: Optional[dict] = Depends(get_optional_current_user),
) -> dict[str, Any]:
    """Train or re-train an opponent clone model and return its model statistics (loss, accuracy, etc.)."""
    opp_clean = player_id.lower().strip()
    user_id = (current_user.get("user_id") if current_user else None)

    # If model is already cached and not forced, return existing stats if valid
    if not force:
        stats = model_repo.get_model_stats(opp_clean)
        path = model_repo.get_model_weights_path(opp_clean)
        if stats and path and path.is_file() and stats.get("val_loss") is not None:
            # Ensure style description is generated and cached in DB if missing
            if not stats.get("style_description"):
                from app.services import commentary_service
                style = commentary_service.describe_clone_style(opp_clean, refresh=True)
                stats["style_description"] = style.get("style_description")
            rating = stats.get("chess_elo") or stats.get("chess_rating") or stats.get("blitz_rating")
            return {
                "status": "cached",
                "player_id": opp_clean,
                "rating": rating,
                "chess_elo": rating,
                "chess_rating": rating,
                "blitz_rating": rating,
                "val_accuracy": stats.get("val_accuracy"),
                "val_loss": stats.get("val_loss"),
                "model_stats": stats,
            }

    try:
        from app.services import training_service
        training_service.run_training_pipeline(opp_clean, trained_by_user_id=user_id)
        stats = model_repo.get_model_stats(opp_clean)
        rating = stats.get("chess_elo") if stats else None
        return {
            "status": "completed",
            "player_id": opp_clean,
            "rating": rating,
            "chess_elo": rating,
            "chess_rating": rating,
            "blitz_rating": rating,
            "val_accuracy": stats.get("val_accuracy") if stats else None,
            "val_loss": stats.get("val_loss") if stats else None,
            "model_stats": stats,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Training failed: {str(e)}")


@router.post("/api/clones/{player_id}/eval")
def evaluate_clone_endpoint(player_id: str) -> dict[str, Any]:
    """Run real move_accuracy evaluation on clone model using player's games and Maia-3 logits."""
    from app.services import training_service
    try:
        return training_service.evaluate_existing_clone(player_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {str(e)}")


@router.post("/api/clones/eval-all")
def evaluate_all_clones_endpoint() -> list[dict[str, Any]]:
    """Scan and run real move_accuracy evaluation across all disk clone models."""
    from app.services import training_service
    return training_service.evaluate_all_clones()


@router.post("/api/clones/{player_id}/benchmark")
@router.get("/api/clones/{player_id}/benchmark")
def benchmark_clone_endpoint(
    player_id: str,
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    """Run full comparative benchmark (Maia-3 vs Clone move accuracy and decision time predictions)."""
    from app.services import training_service
    try:
        return training_service.benchmark_clone_performance(player_id, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Benchmark failed: {str(e)}")


@router.post("/api/clones/{player_id}/benchmark-snapshots")
@router.get("/api/clones/{player_id}/benchmark-snapshots")
def benchmark_clone_snapshots_endpoint(
    player_id: str,
    counts: Optional[str] = Query(default=None, description="Comma-separated snapshot sizes, e.g. 50,100,250,500,1000"),
    limit: int = Query(default=40, ge=1, le=100),
) -> list[dict[str, Any]]:
    """Run comparative benchmark across varying snapshot sample sizes."""
    from app.services import training_service
    snapshot_counts = None
    if counts:
        try:
            snapshot_counts = [int(c.strip()) for c in counts.split(",") if c.strip()]
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid comma-separated integer counts")

    try:
        return training_service.benchmark_snapshot_scaling(player_id, snapshot_counts=snapshot_counts, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Snapshot scaling benchmark failed: {str(e)}")


@router.get("/api/clones/{player_id}/stats")
def get_clone_stats(player_id: str) -> dict[str, Any]:
    """Retrieve usage stats, access counter, and timestamps for a specific model."""
    stats = model_repo.get_model_stats(player_id)
    if not stats:
        raise HTTPException(status_code=404, detail=f"Model for '{player_id}' not found")

    # If val_accuracy is missing, run real evaluation
    if stats.get("val_accuracy") is None:
        try:
            from app.services import training_service
            eval_res = training_service.evaluate_existing_clone(player_id)
            if eval_res and eval_res.get("val_accuracy") is not None:
                stats["val_accuracy"] = eval_res["val_accuracy"]
                stats["val_loss"] = eval_res["val_loss"]
        except Exception:
            pass

    if not stats.get("style_description"):
        try:
            style_resp = commentary_service.describe_clone_style(player_id)
            if style_resp and style_resp.get("style_description"):
                stats["style_description"] = style_resp["style_description"]
        except Exception:
            pass
    return stats


@router.get("/api/clones/{player_id}/past-games")
def get_clone_past_games(
    player_id: str,
    user: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: Optional[dict] = Depends(get_optional_current_user),
) -> list[dict[str, Any]]:
    """Retrieve user's recorded past games against this specific opponent clone."""
    from app.db.repositories import game_repo
    user_handle = (current_user.get("user_id") if current_user else None) or user or "stuffyness"
    return game_repo.get_head_to_head_games(user_handle, player_id, limit=limit)


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
