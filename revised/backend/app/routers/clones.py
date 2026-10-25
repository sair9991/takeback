from fastapi import APIRouter, HTTPException
from app.schemas.clone import PredictStateRequest, PredictStateResponse
from app.services import inference_service

router = APIRouter(tags=["Clones"])


@router.post("/api/predict_next_state", response_model=PredictStateResponse)
@router.post("/api/predict-next-state", response_model=PredictStateResponse)
def predict_next_state(payload: PredictStateRequest):
    """Predict the opponent clone's next move and updated clocks from the current FEN."""
    try:
        return inference_service.predict_clone_move(
            fen=payload.fen,
            opponent_color=payload.opponent_color,
            my_clock=payload.my_clock,
            opponent_clock=payload.opponent_clock,
            opponent_username=payload.opponent_username,
            opponent_elo=payload.opponent_elo,
            my_elo=payload.my_elo,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
