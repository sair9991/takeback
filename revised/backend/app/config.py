import os
from pathlib import Path

CURRENT_FILE = Path(__file__).resolve()
# In container: /app/app/config.py -> parents[1] is /app
# On host: .../revised/backend/app/config.py -> parents[1] is .../revised/backend, parents[2] is .../revised
BACKEND_DIR = CURRENT_FILE.parents[1]
REVISED_DIR = CURRENT_FILE.parents[2] if (CURRENT_FILE.parents[2] / "models").is_dir() else BACKEND_DIR

MODELS_DIR = REVISED_DIR / "models" if (REVISED_DIR / "models").is_dir() else BACKEND_DIR / "models"
MODEL_CODE_DIR = BACKEND_DIR / "app" / "ml"
MAIA3_DIR = BACKEND_DIR / "maia3"

# Load local .env if present
env_candidate = REVISED_DIR / ".env"
if env_candidate.is_file():
    with open(env_candidate, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            if k not in os.environ:
                os.environ[k] = v


class Settings:
    PROJECT_ROOT: Path = REVISED_DIR
    BACKEND_DIR: Path = BACKEND_DIR
    MODELS_DIR: Path = MODELS_DIR
    MODEL_CODE_DIR: Path = MODEL_CODE_DIR
    MAIA3_DIR: Path = MAIA3_DIR

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://chess_user:chess_password@localhost:5432/chess_db",
    )

    STOCKFISH_PATH: str = os.getenv("STOCKFISH_PATH", "")
    OLLAMA_URL: str = os.getenv("OLLAMA_URL", "")
    GEMMA_MODEL_ID: str = os.getenv("GEMMA_MODEL_ID", "gemma2:2b")
    GEMMA_API_URL: str = os.getenv("GEMMA_API_URL", "http://gemma:8080")
    GEMMA_TIMEOUT: float = float(os.getenv("GEMMA_TIMEOUT", "60.0"))

    DEFAULT_DEVICE: str = os.getenv("DEFAULT_DEVICE", "cpu")

    # Authentication & OAuth
    JWT_SECRET: str = os.getenv("JWT_SECRET", "chess-clone-dev-secret-key-32chars-min!!")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_DAYS: int = int(os.getenv("JWT_EXPIRE_DAYS", "7"))
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback")
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:3000")
    COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "false").lower() == "true"


settings = Settings()
