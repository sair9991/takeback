import asyncio
import json
from contextlib import asynccontextmanager
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
try:
    import chess
    import chess.svg
except ImportError:
    chess = None
import clone_service
import evaluator
import gemma_service
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


@app.get("/api/games/{game_id}")
def get_game_detail(game_id: str):
    """Fetch game metadata along with its chronological moves, cached odds, and Gemma commentary."""
    game = helper.query_one("SELECT * FROM games WHERE game_id = ? OR id = ?", (game_id, game_id))
    if not game:
        raise HTTPException(404, "Game not found")
    actual_gid = game.get("game_id") or str(game.get("id"))
    moves = helper.query(
        "SELECT ply, side, move, time_remaining, clock_str FROM moves WHERE game_id = ? ORDER BY ply ASC",
        (actual_gid,),
    )
    odds = []
    eval_error = None
    try:
        odds = evaluator.cache_game_odds(actual_gid, game.get("player_id"))
    except Exception as e:
        eval_error = str(e)

    commentary = []
    narrative = ""
    tags = []
    gemma_error = None
    try:
        c, n = gemma_service.cache_game_commentary_and_narrative(actual_gid, game.get("player_id"))
        commentary = c
        narrative = n.get("narrative", "") if isinstance(n, dict) else str(n)
        tags = n.get("tags", []) if isinstance(n, dict) else []
    except RuntimeError as e:
        gemma_error = str(e)

    return {
        **helper.format_game(game),
        "moves": moves,
        "odds": odds,
        "commentary": commentary,
        "narrative": narrative,
        "tags": tags,
        "error": gemma_error or eval_error,
    }


@app.get("/api/games/{game_id}/moves")
def get_game_moves(game_id: str):
    """Fetch real chronological moves and clocks for a game."""
    sql = "SELECT ply, side, move, time_remaining, clock_str FROM moves WHERE game_id = ? ORDER BY ply ASC"
    return helper.query(sql, (game_id,))


@app.get("/api/games/{game_id}/thumbnail.svg")
@app.get("/api/games/{game_id}/thumbnail")
def get_game_thumbnail(game_id: str, ply: int = None):
    """
    Generate an SVG board image for a game card on the fly.
    Picks a dynamic, authentic middlegame moment (e.g. ply 14-24) to showcase the game.
    """
    if chess is None:
        raise HTTPException(500, "python-chess is not installed")

    game = helper.query_one("SELECT * FROM games WHERE game_id = ? OR id = ?", (game_id, game_id))
    actual_gid = (game.get("game_id") if game else None) or game_id
    moves = helper.query("SELECT move FROM moves WHERE game_id = ? ORDER BY ply ASC", (actual_gid,))

    board = chess.Board()
    if moves:
        if ply is not None:
            target_ply = min(max(0, ply), len(moves))
        else:
            seed = sum(ord(c) for c in str(actual_gid))
            min_ply = min(10, len(moves))
            max_ply = min(26, len(moves))
            target_ply = min_ply + (seed % (max(1, max_ply - min_ply + 1)))

        for i in range(target_ply):
            try:
                board.push_san(moves[i]["move"])
            except Exception:
                break

    player_color = (game.get("player_color") if game else "white") or "white"
    orientation = chess.WHITE if player_color.lower() == "white" else chess.BLACK

    svg_data = chess.svg.board(
        board=board,
        orientation=orientation,
        size=300,
        coordinates=False,
        colors={"square light": "#f0d9b5", "square dark": "#b58863"},
    )
    return Response(
        content=svg_data,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=604800"},
    )


@app.get("/api/users/{username}/analyzed-games")
def get_analyzed_games(username: str, limit: int = 50, offset: int = 0):
    sql = """
        SELECT g.*, a.created_at as analyzed_at FROM analyzed_games a
        JOIN games g ON (a.game_id = g.game_id OR a.game_id = CAST(g.id AS TEXT))
        WHERE a.user_id = ? ORDER BY a.created_at DESC LIMIT ? OFFSET ?
    """
    return [helper.format_game(r) for r in helper.query(sql, (username, limit, offset))]


@app.post("/api/users/{username}/analyze/{game_id}")
def analyze_game(username: str, game_id: str, background_tasks: BackgroundTasks, opponent: str = None):
    game = helper.query_one("SELECT opponent_username FROM games WHERE game_id = ? OR id = ?", (game_id, game_id))
    opp = (game.get("opponent_username") if game else None) or opponent or "Opponent"

    if queue_manager.is_cached(opp):
        helper.execute("INSERT OR IGNORE INTO analyzed_games (user_id, game_id) VALUES (?, ?)", (username, game_id))
        background_tasks.add_task(evaluator.cache_game_odds, game_id, username)
        background_tasks.add_task(gemma_service.cache_game_commentary_and_narrative, game_id, username)
        return {"cached": True, "status": "ready", "opponent": opp}

    job_id = queue_manager.enqueue(opp, username, game_id)
    return {
        "cached": False,
        "status": "queued",
        "job_id": job_id,
        "opponent": opp,
        "stream_url": f"/api/analysis/stream/{job_id}",
    }


@app.get("/api/users/{username}/search-games")
def search_games(username: str, q: str):
    """Semantic and tag search over analyzed games via Gemma narrative and tags."""
    q_clean = f"%{q.strip().lower()}%"
    sql = """
        SELECT g.*, a.narrative, a.narrative_tags, a.created_at as analyzed_at
        FROM analyzed_games a
        JOIN games g ON (a.game_id = g.game_id OR a.game_id = CAST(g.id AS TEXT))
        WHERE a.user_id = ? AND (
            LOWER(COALESCE(a.narrative, '')) LIKE ? OR
            LOWER(COALESCE(a.narrative_tags, '')) LIKE ? OR
            LOWER(COALESCE(g.opponent_username, '')) LIKE ? OR
            LOWER(COALESCE(g.result, '')) LIKE ?
        )
        ORDER BY a.created_at DESC
    """
    rows = helper.query(sql, (username, q_clean, q_clean, q_clean, q_clean))
    return [
        {
            **helper.format_game(r),
            "narrative": r.get("narrative"),
            "tags": json.loads(r.get("narrative_tags") or "[]"),
        }
        for r in rows
    ]


@app.get("/api/analysis/stream/{job_id}")
async def stream_training(job_id: str):
    return StreamingResponse(queue_manager.stream(job_id), media_type="text/event-stream")


@app.post("/api/predict_next_state", response_model=clone_service.PredictStateResponse)
@app.post("/api/predict-next-state", response_model=clone_service.PredictStateResponse)
def predict_next_state(payload: clone_service.PredictStateRequest):
    """Predict the opponent clone's next move and updated clocks from the current FEN."""
    try:
        return clone_service.predict_clone_move(
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
