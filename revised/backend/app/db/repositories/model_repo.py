from pathlib import Path
from typing import Any, Optional
from app.config import settings
from app.db.connection import query, query_one, execute


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


def register_model_weights(
    player_id: str,
    weights_path: str,
    trained_by_user_id: Optional[str] = None,
) -> None:
    """Upsert model weights location and author in models table."""
    opp_clean = player_id.lower().strip()
    sql = """
        INSERT INTO models (player_id, weights_path, trained_by_user_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (player_id)
        DO UPDATE SET
            weights_path = EXCLUDED.weights_path,
            trained_by_user_id = COALESCE(EXCLUDED.trained_by_user_id, models.trained_by_user_id),
            updated_at = CURRENT_TIMESTAMP
    """
    execute(sql, (opp_clean, weights_path, trained_by_user_id))


def record_model_access(
    player_id: str,
    accessed_by_user_id: Optional[str] = None,
    think_time: Optional[float] = None,
) -> None:
    """Increment model access count and log audit entry."""
    opp_clean = player_id.lower().strip()
    sql_update = """
        UPDATE models
        SET access_count = access_count + 1,
            last_accessed_at = CURRENT_TIMESTAMP
        WHERE LOWER(player_id) = %s
    """
    execute(sql_update, (opp_clean,))

    sql_log = """
        INSERT INTO model_access_logs (player_id, accessed_by_user_id, think_time)
        VALUES (%s, %s, %s)
    """
    execute(sql_log, (opp_clean, accessed_by_user_id, think_time))


def get_model_stats(player_id: str) -> Optional[dict[str, Any]]:
    """Return model metadata, usage counters, and timestamps."""
    opp_clean = player_id.lower().strip()
    sql = """
        SELECT player_id, trained_by_user_id, model_name, val_accuracy, val_loss,
               access_count, last_accessed_at, created_at, updated_at
        FROM models
        WHERE LOWER(player_id) = %s
    """
    return query_one(sql, (opp_clean,))


def get_model_access_logs(player_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Return paginated access logs for a specific model."""
    opp_clean = player_id.lower().strip()
    sql = """
        SELECT id, player_id, accessed_by_user_id, think_time, accessed_at
        FROM model_access_logs
        WHERE LOWER(player_id) = %s
        ORDER BY accessed_at DESC
        LIMIT %s OFFSET %s
    """
    return query(sql, (opp_clean, limit, offset))


def get_user_models_stats(user_id: str) -> dict[str, Any]:
    """Return access counts and stats for all models trained by or matching a user."""
    uid_clean = user_id.lower().strip()
    sql_models = """
        SELECT player_id, trained_by_user_id, model_name, val_accuracy, val_loss,
               access_count, last_accessed_at, created_at
        FROM models
        WHERE LOWER(trained_by_user_id) = %s OR LOWER(player_id) = %s
        ORDER BY access_count DESC, created_at DESC
    """
    models = query(sql_models, (uid_clean, uid_clean))
    total_accesses = sum(int(m.get("access_count") or 0) for m in models)

    sql_recent_logs = """
        SELECT l.id, l.player_id, l.accessed_by_user_id, l.think_time, l.accessed_at
        FROM model_access_logs l
        JOIN models m ON LOWER(l.player_id) = LOWER(m.player_id)
        WHERE LOWER(m.trained_by_user_id) = %s OR LOWER(m.player_id) = %s
        ORDER BY l.accessed_at DESC
        LIMIT 20
    """
    recent_logs = query(sql_recent_logs, (uid_clean, uid_clean))

    return {
        "user_id": user_id,
        "total_models": len(models),
        "total_access_count": total_accesses,
        "models": models,
        "recent_access_logs": recent_logs,
    }


def list_models() -> list[dict[str, Any]]:
    """Return all available models ordered by total usage."""
    sql = """
        SELECT player_id, trained_by_user_id, model_name, val_accuracy, val_loss,
               access_count, last_accessed_at, created_at
        FROM models
        ORDER BY access_count DESC, updated_at DESC
    """
    return query(sql)
