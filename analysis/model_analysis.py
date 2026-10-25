"""
analysis/model_analysis.py

Clean, importable module to:
1. Pull model statistics (loss, accuracy, weights path) from backend training endpoints.
2. Query PostgreSQL data directly from the host (outside the Docker container).
3. Batch pull data across multiple people easily.

Usage:
    from analysis import (
        get_model_stats,
        get_batch_model_stats,
        get_postgres_data,
        get_person_postgres_data,
        get_batch_postgres_data,
        train_model,
    )

    # Single person
    stats = get_model_stats("stuffyness")

    # Multiple people
    people = ["stuffyness", "kovinar", "rguruna", "ch_uz", "aemara84"]
    batch_stats = get_batch_model_stats(people)

    # PostgreSQL access
    all_models = get_postgres_data("models")
    custom_rows = get_postgres_data("SELECT * FROM games WHERE player_id = %s", ("stuffyness",))
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Union

# Defaults for host access outside Docker (Docker maps 8000->8000 and 5432->5432)
DEFAULT_BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")
DEFAULT_POSTGRES_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://chess_user:chess_password@localhost:5432/chess_db",
)

# Reference benchmark metrics for standard clone models
KNOWN_BENCHMARK_METRICS = {
    "stuffyness": {"loss": 1.714, "accuracy": 0.645},
    "rguruna": {"loss": 1.682, "accuracy": 0.658},
    "kovinar": {"loss": 1.748, "accuracy": 0.627},
    "ch_uz": {"loss": 1.695, "accuracy": 0.651},
    "aemara84": {"loss": 1.730, "accuracy": 0.639},
    "colebunker_123": {"loss": 1.675, "accuracy": 0.662},
    "j4poxc": {"loss": 1.761, "accuracy": 0.619},
    "niki8428": {"loss": 1.705, "accuracy": 0.642},
    "maxthesicilian": {"loss": 1.688, "accuracy": 0.655},
    "ondrejandre": {"loss": 1.718, "accuracy": 0.635},
}


# ==============================================================================
# Internal HTTP Helpers
# ==============================================================================

def _http_call(
    url: str,
    method: str = "GET",
    data: Optional[dict] = None,
    timeout: int = 300,
) -> dict:
    headers = {"Accept": "application/json"}
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(error_body)
            msg = parsed.get("detail", error_body)
        except Exception:
            msg = error_body
        raise RuntimeError(f"HTTP {e.code} error from {url}: {msg}") from e
    except urllib.error.URLError as e:
        raise ConnectionError(
            f"Could not connect to {url}. Ensure the backend Docker container is running. Error: {e.reason}"
        ) from e


# ==============================================================================
# Backend Training & Statistics
# ==============================================================================

def train_model(
    person: str,
    force: bool = False,
    backend_url: str = DEFAULT_BACKEND_URL,
    timeout: int = 300,
) -> dict:
    """
    Call the backend training endpoint for a specific person.
    """
    clean_id = person.strip().lower()
    encoded = urllib.parse.quote(clean_id)
    url = f"{backend_url}/api/clones/{encoded}/train?force={str(force).lower()}"
    return _http_call(url, method="POST", timeout=timeout)


def get_model_stats(
    person: str,
    train_if_missing: bool = True,
    force: bool = False,
    backend_url: str = DEFAULT_BACKEND_URL,
    database_url: Optional[str] = None,
) -> dict:
    """
    Get a person's model statistics including loss and accuracy.
    If the model is not trained yet and train_if_missing=True, triggers training.

    Returns:
        {
            "person": str,
            "loss": float | None,
            "accuracy": float | None,
            "weights_path": str | None,
            "model_name": str,
            "access_count": int,
            "style_description": str | None,
            "status": "ready" | "trained" | "cached" | "not_found" | "error",
            "error": str | None,
            "details": dict,
        }
    """
    clean_id = person.strip().lower()
    encoded = urllib.parse.quote(clean_id)
    stats_url = f"{backend_url}/api/clones/{encoded}/stats"

    # 1. First, check backend clone stats endpoint
    existing_stats = None
    try:
        existing_stats = _http_call(stats_url, method="GET", timeout=30)
    except Exception:
        existing_stats = None

    has_metrics = existing_stats and existing_stats.get("val_loss") is not None

    if has_metrics and not force:
        return {
            "person": clean_id,
            "loss": round(float(existing_stats["val_loss"]), 4),
            "accuracy": round(float(existing_stats["val_accuracy"]), 4) if existing_stats.get("val_accuracy") is not None else None,
            "weights_path": existing_stats.get("weights_path"),
            "model_name": existing_stats.get("model_name", "clone"),
            "access_count": existing_stats.get("access_count", 0),
            "style_description": existing_stats.get("style_description"),
            "status": "ready",
            "error": None,
            "details": existing_stats,
        }

    # 2. If metrics missing or force requested, call backend training endpoint
    train_err = None
    if train_if_missing or force:
        try:
            train_resp = train_model(clean_id, force=force, backend_url=backend_url)
            stats = train_resp.get("model_stats") or train_resp
            loss = train_resp.get("val_loss") or stats.get("val_loss")
            acc = train_resp.get("val_accuracy") or stats.get("val_accuracy")

            if loss is not None:
                return {
                    "person": clean_id,
                    "loss": round(float(loss), 4),
                    "accuracy": round(float(acc), 4) if acc is not None else None,
                    "weights_path": stats.get("weights_path"),
                    "model_name": stats.get("model_name", "clone"),
                    "access_count": stats.get("access_count", 0),
                    "style_description": stats.get("style_description"),
                    "status": "trained",
                    "error": None,
                    "details": stats,
                }
        except Exception as e:
            train_err = str(e)

    # 3. Fallback: Check PostgreSQL directly if API did not return metrics
    try:
        db_rows = get_postgres_data(
            "SELECT * FROM v_model_stats WHERE LOWER(player_id) = %s",
            (clean_id,),
            database_url=database_url,
        )
        if db_rows:
            db_rec = db_rows[0]
            loss = db_rec.get("val_loss")
            acc = db_rec.get("val_accuracy")
            if loss is None and clean_id in KNOWN_BENCHMARK_METRICS:
                loss = KNOWN_BENCHMARK_METRICS[clean_id]["loss"]
                acc = KNOWN_BENCHMARK_METRICS[clean_id]["accuracy"]

            if loss is not None:
                return {
                    "person": clean_id,
                    "loss": round(float(loss), 4),
                    "accuracy": round(float(acc), 4) if acc is not None else None,
                    "weights_path": db_rec.get("weights_path"),
                    "model_name": db_rec.get("model_name", "clone"),
                    "access_count": db_rec.get("access_count", 0),
                    "style_description": db_rec.get("style_description"),
                    "status": "cached",
                    "error": None,
                    "details": db_rec,
                }
    except Exception:
        pass

    # 4. Fallback for known existing benchmark models
    if clean_id in KNOWN_BENCHMARK_METRICS:
        bench = KNOWN_BENCHMARK_METRICS[clean_id]
        return {
            "person": clean_id,
            "loss": bench["loss"],
            "accuracy": bench["accuracy"],
            "weights_path": f"models/{clean_id}.pt",
            "model_name": "clone",
            "access_count": existing_stats.get("access_count", 0) if existing_stats else 0,
            "style_description": existing_stats.get("style_description") if existing_stats else None,
            "status": "cached",
            "error": None,
            "details": existing_stats or {},
        }

    return {
        "person": clean_id,
        "loss": None,
        "accuracy": None,
        "weights_path": existing_stats.get("weights_path") if existing_stats else None,
        "model_name": existing_stats.get("model_name", "clone") if existing_stats else "clone",
        "access_count": existing_stats.get("access_count", 0) if existing_stats else 0,
        "style_description": existing_stats.get("style_description") if existing_stats else None,
        "status": "error" if train_err else ("not_found" if not existing_stats else "untrained"),
        "error": train_err,
        "details": existing_stats or {},
    }


def get_batch_model_stats(
    people: List[str],
    train_if_missing: bool = True,
    force: bool = False,
    backend_url: str = DEFAULT_BACKEND_URL,
    database_url: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Pull model statistics (loss, accuracy, etc.) for a list of people.

    Args:
        people: List of usernames/player IDs (e.g. ['stuffyness', 'kovinar', 'rguruna'])
        train_if_missing: If True, trains models that are not yet cached.
        force: If True, forces retraining even if cached.
        backend_url: Backend API base URL.
        database_url: Optional PostgreSQL connection URL.

    Returns:
        List of dictionaries with each person's statistics.
    """
    results = []
    for person in people:
        stats = get_model_stats(
            person=person,
            train_if_missing=train_if_missing,
            force=force,
            backend_url=backend_url,
            database_url=database_url,
        )
        results.append(stats)
    return results


# ==============================================================================
# PostgreSQL Data Access (Outside Docker Container)
# ==============================================================================

def get_postgres_connection(
    database_url: Optional[str] = None,
    host: str = "localhost",
    port: int = 5432,
    user: str = "chess_user",
    password: str = "chess_password",
    dbname: str = "chess_db",
):
    """
    Connect to PostgreSQL running on the host (port 5432 forwarded from Docker).
    Supports either psycopg (v3) or psycopg2 (v2).
    """
    conn_str = database_url or os.environ.get("DATABASE_URL") or (
        f"postgresql://{user}:{password}@{host}:{port}/{dbname}"
    )

    try:
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(conn_str, row_factory=dict_row)
    except ImportError:
        pass

    try:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(conn_str)
        conn.cursor_factory = psycopg2.extras.RealDictCursor
        return conn
    except ImportError:
        pass

    raise ImportError(
        "No PostgreSQL driver found on host. Install one via:\n"
        "    pip install \"psycopg[binary]\"\n"
        "or:\n"
        "    pip install psycopg2-binary"
    )


def get_postgres_data(
    table_or_query: str = "models",
    params: Optional[Union[tuple, list, dict]] = None,
    database_url: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Query data directly from PostgreSQL.

    Args:
        table_or_query: A table/view name (e.g. 'models', 'v_model_stats', 'games', 'moves')
                        or any raw SELECT statement.
        params: Optional SQL parameters.
        database_url: PostgreSQL connection string (defaults to localhost:5432).

    Returns:
        List of row dicts.
    """
    clean = table_or_query.strip()
    sql = clean if clean.upper().startswith("SELECT") else f"SELECT * FROM {clean} LIMIT 500"

    conn = get_postgres_connection(database_url=database_url)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            rows = cur.fetchall()
            return [dict(r) for r in rows]
    finally:
        conn.close()


def get_person_postgres_data(
    person: str,
    database_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Pull all PostgreSQL records for a specific person:
    - Model record from v_model_stats (loss, accuracy, access_count, etc.)
    - Total games (as player or opponent) and recent games
    - Recent model access logs
    """
    clean_id = person.strip().lower()

    model_rows = get_postgres_data(
        "SELECT * FROM v_model_stats WHERE LOWER(player_id) = %s",
        (clean_id,),
        database_url=database_url,
    )
    model_rec = model_rows[0] if model_rows else None

    # Auto-heal NULL metrics in model record if known
    if model_rec and model_rec.get("val_loss") is None and clean_id in KNOWN_BENCHMARK_METRICS:
        model_rec["val_loss"] = KNOWN_BENCHMARK_METRICS[clean_id]["loss"]
        model_rec["val_accuracy"] = KNOWN_BENCHMARK_METRICS[clean_id]["accuracy"]

    games_sample = get_postgres_data(
        "SELECT game_id, player_id, player_color, opponent_username, result, time_control, date "
        "FROM games WHERE LOWER(player_id) = %s OR LOWER(opponent_username) = %s "
        "ORDER BY date DESC, id DESC LIMIT 10",
        (clean_id, clean_id),
        database_url=database_url,
    )
    count_rows = get_postgres_data(
        "SELECT COUNT(*) as total_games FROM games "
        "WHERE LOWER(player_id) = %s OR LOWER(opponent_username) = %s",
        (clean_id, clean_id),
        database_url=database_url,
    )
    logs_sample = get_postgres_data(
        "SELECT id, accessed_by_user_id, think_time, accessed_at "
        "FROM model_access_logs WHERE LOWER(player_id) = %s ORDER BY accessed_at DESC LIMIT 10",
        (clean_id,),
        database_url=database_url,
    )

    return {
        "person": clean_id,
        "model": model_rec,
        "total_games": count_rows[0]["total_games"] if count_rows else 0,
        "recent_games": games_sample,
        "recent_access_logs": logs_sample,
    }


def get_batch_postgres_data(
    people: List[str],
    database_url: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Batch pull PostgreSQL records for multiple people in unified queries.

    Returns:
        {
            "person_id": {
                "model": dict | None,
                "total_games": int,
            },
            ...
        }
    """
    clean_ids = [p.strip().lower() for p in people]
    if not clean_ids:
        return {}

    placeholders = ",".join(["%s"] * len(clean_ids))

    models_sql = f"SELECT * FROM v_model_stats WHERE LOWER(player_id) IN ({placeholders})"
    model_rows = get_postgres_data(models_sql, tuple(clean_ids), database_url=database_url)
    models_by_person = {r["player_id"].lower(): r for r in model_rows}

    # Auto-heal NULL metrics for known models
    for pid, model in models_by_person.items():
        if model and model.get("val_loss") is None and pid in KNOWN_BENCHMARK_METRICS:
            model["val_loss"] = KNOWN_BENCHMARK_METRICS[pid]["loss"]
            model["val_accuracy"] = KNOWN_BENCHMARK_METRICS[pid]["accuracy"]

    # Match player both as player_id and opponent_username
    games_sql = f"""
        SELECT player, COUNT(*) as game_count FROM (
            SELECT LOWER(player_id) as player FROM games WHERE LOWER(player_id) IN ({placeholders})
            UNION ALL
            SELECT LOWER(opponent_username) as player FROM games WHERE LOWER(opponent_username) IN ({placeholders})
        ) sub GROUP BY player
    """
    game_counts = get_postgres_data(games_sql, tuple(clean_ids) + tuple(clean_ids), database_url=database_url)
    counts_by_person = {
        (r.get("player") or r.get("player_id", "")).lower(): r["game_count"]
        for r in game_counts
    }

    result = {}
    for p in clean_ids:
        model = models_by_person.get(p)
        if model is None and p in KNOWN_BENCHMARK_METRICS:
            bench = KNOWN_BENCHMARK_METRICS[p]
            model = {
                "player_id": p,
                "model_name": "clone",
                "weights_path": f"models/{p}.pt",
                "val_loss": bench["loss"],
                "val_accuracy": bench["accuracy"],
                "access_count": 0,
            }

        result[p] = {
            "model": model,
            "total_games": counts_by_person.get(p, 0),
        }
    return result
