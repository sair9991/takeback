import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth, games, analysis, clones, stream
from app.db.connection import close_pool
from app.workers import queue_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
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

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
