import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import helper
import queue_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(queue_manager.worker())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/users/{username}/games")
def get_user_games(username: str, limit: int = 50, offset: int = 0):
    rows = helper.query(
        "SELECT * FROM games WHERE player_id = ? ORDER BY date DESC, id DESC LIMIT ? OFFSET ?",
        (username, limit, offset),
    )
    return [helper.format_game(r) for r in rows]


@app.get("/api/users/{username}/analyzed-games")
def get_analyzed_games(username: str, limit: int = 50, offset: int = 0):
    sql = """
        SELECT g.*, a.created_at as analyzed_at FROM analyzed_games a
        JOIN games g ON (a.game_id = g.game_id OR a.game_id = CAST(g.id AS TEXT))
        WHERE a.user_id = ? ORDER BY a.created_at DESC LIMIT ? OFFSET ?
    """
    return [helper.format_game(r) for r in helper.query(sql, (username, limit, offset))]


@app.post("/api/users/{username}/analyze/{game_id}")
def analyze_game(username: str, game_id: str):
    game = helper.query_one("SELECT opponent_username FROM games WHERE game_id = ? OR id = ?", (game_id, game_id))
    if not game:
        raise HTTPException(404, "Game not found")
    opp = game.get("opponent_username") or "Opponent"

    if queue_manager.is_cached(opp):
        helper.execute("INSERT OR IGNORE INTO analyzed_games (user_id, game_id) VALUES (?, ?)", (username, game_id))
        return {"cached": True, "status": "ready", "opponent": opp}

    job_id = queue_manager.enqueue(opp, username, game_id)
    return {
        "cached": False,
        "status": "queued",
        "job_id": job_id,
        "opponent": opp,
        "stream_url": f"/api/analysis/stream/{job_id}",
    }


@app.get("/api/analysis/stream/{job_id}")
async def stream_training(job_id: str):
    return StreamingResponse(queue_manager.stream(job_id), media_type="text/event-stream")
