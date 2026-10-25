from pathlib import Path
from typing import Any, Optional
from app.config import settings
from app.db.connection import query, query_one, execute, transaction


def get_model_weights_path(player_id: str) -> Optional[Path]:
    """Resolve trained weights checkpoint for an opponent."""
    opp_key = player_id.lower().strip()
    sql = "SELECT weights_path FROM models WHERE LOWER(player_id) = %s"
    row = query_one(sql, (opp_key,))
    if row and row.get("weights_path"):
        p = Path(row["weights_path"])
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
    """Atomically record model access audit entry in 3NF ledger table."""
    opp_clean = player_id.lower().strip()
    weights_rel = f"models/{opp_clean}.pt"

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO models (player_id, weights_path)
                VALUES (%s, %s)
                ON CONFLICT (player_id) DO NOTHING
                """,
                (opp_clean, weights_rel),
            )
            cur.execute(
                """
                INSERT INTO model_access_logs (player_id, accessed_by_user_id, think_time)
                VALUES (%s, %s, %s)
                """,
                (opp_clean, accessed_by_user_id, think_time),
            )


def get_model_stats(player_id: str) -> Optional[dict[str, Any]]:
    """Return model metadata, style description, and live aggregated access counts from 3NF view."""
    opp_clean = player_id.lower().strip()
    sql = """
        SELECT player_id, trained_by_user_id, model_name, style_description,
               val_accuracy, val_loss, access_count, last_accessed_at, created_at, updated_at
        FROM v_model_stats
        WHERE LOWER(player_id) = %s
    """
    return query_one(sql, (opp_clean,))


def update_model_style(
    player_id: str,
    style_description: str,
    embedding: Optional[list[float]] = None,
) -> None:
    """Persist generated playing style description and vector embedding for a model."""
    opp_clean = player_id.lower().strip()
    if embedding:
        vec_str = f"[{','.join(str(f) for f in embedding)}]"
        sql = """
            UPDATE models
            SET style_description = %s,
                embedding = %s::vector,
                updated_at = CURRENT_TIMESTAMP
            WHERE LOWER(player_id) = %s
        """
        execute(sql, (style_description, vec_str, opp_clean))
    else:
        sql = """
            UPDATE models
            SET style_description = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE LOWER(player_id) = %s
        """
        execute(sql, (style_description, opp_clean))


def search_clones_by_style(
    query_text: str,
    query_embedding: Optional[list[float]] = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search trained clones by style persona using semantic embeddings and keyword matching."""
    if query_embedding:
        vec_str = f"[{','.join(str(f) for f in query_embedding)}]"
        sql = """
            SELECT m.player_id, m.model_name, m.style_description, m.val_accuracy,
                   COALESCE(stats.access_count, 0) AS access_count,
                   ROUND((1.0 - (m.embedding <=> %s::vector))::numeric, 4) AS similarity_score
            FROM models m
            LEFT JOIN (
                SELECT player_id, COUNT(*) AS access_count
                FROM model_access_logs
                GROUP BY player_id
            ) stats ON m.player_id = stats.player_id
            WHERE m.embedding IS NOT NULL
            ORDER BY m.embedding <=> %s::vector
            LIMIT %s
        """
        rows = query(sql, (vec_str, vec_str, limit))
        if rows:
            return rows

    # fallback to ILIKE text pattern match
    q_clean = f"%{query_text.strip().lower()}%"
    sql_text = """
        SELECT m.player_id, m.model_name, m.style_description, m.val_accuracy,
               COALESCE(stats.access_count, 0) AS access_count,
               NULL::float AS similarity_score
        FROM models m
        LEFT JOIN (
            SELECT player_id, COUNT(*) AS access_count
            FROM model_access_logs
            GROUP BY player_id
        ) stats ON m.player_id = stats.player_id
        WHERE LOWER(COALESCE(m.style_description, '')) LIKE %s
           OR LOWER(m.player_id) LIKE %s
           OR LOWER(m.model_name) LIKE %s
        ORDER BY access_count DESC
        LIMIT %s
    """
    return query(sql_text, (q_clean, q_clean, q_clean, limit))


def get_clone_game_metrics(player_id: str) -> dict[str, Any]:
    """Gather match statistics, tactical tags, and think-time metrics for style analysis."""
    opp_clean = player_id.lower().strip()

    think_sql = """
        SELECT ROUND(AVG(think_time)::numeric, 2) as avg_think_time,
               COUNT(*) as moves_played
        FROM model_access_logs
        WHERE LOWER(player_id) = %s
    """
    think_data = query_one(think_sql, (opp_clean,)) or {}

    games_sql = """
        SELECT result, player_color, opponent_username, time_control
        FROM games
        WHERE LOWER(player_id) = %s OR LOWER(opponent_username) = %s
        ORDER BY date DESC, id DESC
        LIMIT 40
    """
    game_rows = query(games_sql, (opp_clean, opp_clean))

    tags_sql = """
        SELECT DISTINCT t.tag
        FROM analysis_tags t
        JOIN analyzed_games a ON t.analysis_id = a.id
        JOIN games g ON a.game_id = g.game_id
        WHERE LOWER(g.player_id) = %s OR LOWER(g.opponent_username) = %s
        LIMIT 15
    """
    tag_rows = query(tags_sql, (opp_clean, opp_clean))

    return {
        "player_id": opp_clean,
        "avg_think_time": float(think_data.get("avg_think_time") or 1.8),
        "total_moves_logged": int(think_data.get("moves_played") or 0),
        "sample_games": game_rows,
        "sample_tags": [r["tag"] for r in tag_rows],
    }


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
    """Return aggregated access statistics for all models created by or matching a user."""
    uid_clean = user_id.lower().strip()
    sql_models = """
        SELECT player_id, trained_by_user_id, model_name, val_accuracy, val_loss,
               access_count, last_accessed_at, created_at
        FROM v_model_stats
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
    """Return all available models ordered by dynamic access count."""
    sql = """
        SELECT player_id, trained_by_user_id, model_name, style_description,
               val_accuracy, val_loss, access_count, last_accessed_at, created_at
        FROM v_model_stats
        ORDER BY access_count DESC, updated_at DESC
    """
    return query(sql)
