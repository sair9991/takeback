import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.routers import auth, games, analysis, clones, stream
from app.db.connection import close_pool, execute
from app.workers import queue_manager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure database vector columns are unconstrained for full Gemma compatibility
    try:
        execute("ALTER TABLE models ALTER COLUMN embedding TYPE vector;")
        execute("ALTER TABLE analyzed_games ALTER COLUMN embedding TYPE vector;")
    except Exception as e:
        logger.debug("Database vector migration notice: %s", e)

    # Ensure chess_elo column and updated v_model_stats view exist
    try:
        from app.db.repositories import model_repo
        model_repo.ensure_schema_upgrades()
    except Exception as e:
        logger.debug("Database schema upgrade notice: %s", e)

    # Start background worker for training pipeline
    worker_task = asyncio.create_task(queue_manager.worker())
    yield
    # Shutdown
    worker_task.cancel()
    close_pool()


app = FastAPI(
    title="Chess Clone & Analysis Engine API",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS configuration - explicit origins required when allow_credentials=True
origins = [
    settings.FRONTEND_URL,
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in set(origins) if o],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API Routers
app.include_router(auth.router)
app.include_router(games.router)
app.include_router(analysis.router)
app.include_router(clones.router)
app.include_router(stream.router)


@app.get("/health")
def healthcheck():
    return {"status": "ok", "version": "2.0.0"}
