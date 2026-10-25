from pathlib import Path
from typing import Any, Optional
from app.config import settings
from app.db.connection import query_one, execute


def get_model_weights_path(player_id: str) -> Optional[Path]:
    """Resolve trained weights checkpoint for an opponent or return newest clone."""
    opp_key = player_id.lower().strip()
    sql = "SELECT weights_path FROM models WHERE LOWER(player_id) = %s"
    row = query_one(sql, (opp_key,))
    if row and row.get("weights_path"):
        p = Path(row["weights_path"])
        if not p.is_absolute():
            p = settings.PROJECT_ROOT / p
        if p.is_file():
            return p

    # fallback when player clone is not yet trained
    latest = query_one("SELECT weights_path FROM models ORDER BY updated_at DESC, created_at DESC LIMIT 1")
    if latest and latest.get("weights_path"):
        p = Path(latest["weights_path"])
        if not p.is_absolute():
            p = settings.PROJECT_ROOT / p
        if p.is_file():
            return p

    return None


def register_model_weights(player_id: str, weights_path: str) -> None:
    """Upsert model weights location in models table."""
    opp_clean = player_id.lower().strip()
    sql = """
        INSERT INTO models (player_id, weights_path)
        VALUES (%s, %s)
        ON CONFLICT (player_id)
        DO UPDATE SET weights_path = EXCLUDED.weights_path, updated_at = CURRENT_TIMESTAMP
    """
    execute(sql, (opp_clean, weights_path))
