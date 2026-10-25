from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.workers import queue_manager

router = APIRouter(tags=["Stream"])


@router.get("/api/analysis/stream/{job_id}")
async def stream_training(job_id: str):
    return StreamingResponse(
        queue_manager.stream(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
