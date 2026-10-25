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
    fetch_err = None
    try:
        existing_stats = _http_call(stats_url, method="GET", timeout=30)
    except Exception as e:
        existing_stats = None
        fetch_err = str(e)

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

    # 3. Check PostgreSQL directly if API did not return metrics
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

    return {
        "person": clean_id,
        "loss": None,
        "accuracy": None,
        "weights_path": existing_stats.get("weights_path") if existing_stats else None,
        "model_name": existing_stats.get("model_name", "clone") if existing_stats else "clone",
        "access_count": existing_stats.get("access_count", 0) if existing_stats else 0,
        "style_description": existing_stats.get("style_description") if existing_stats else None,
        "status": "error" if (train_err or fetch_err) else ("not_found" if not existing_stats else "untrained"),
        "error": train_err or fetch_err,
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
        result[p] = {
            "model": models_by_person.get(p),
            "total_games": counts_by_person.get(p, 0),
        }
    return result


# ==============================================================================
# Model Comparative Benchmarks (Maia-3 Baseline vs. Clone & Time Predictions)
# ==============================================================================

def benchmark_model(
    person: str,
    limit_games: int = 50,
    backend_url: str = DEFAULT_BACKEND_URL,
    timeout: int = 600,
) -> Dict[str, Any]:
    """
    Run full comparative benchmark on real games and models for a specific person.
    Evaluates:
      1. Move Prediction: Baseline Maia-3 vs Clone Model (Top-1 %, Top-3 %, Cross-Entropy Loss).
      2. Decision Time Prediction: Log-normal tempo head vs actual move clocks.

    Strict mode: Connects directly to backend API. Raises ConnectionError or RuntimeError
    if the service is unreachable. No fallbacks or synthetic mock data.
    """
    clean_id = person.strip().lower()
    encoded = urllib.parse.quote(clean_id)
    url = f"{backend_url}/api/clones/{encoded}/benchmark?limit={int(limit_games)}"
    return _http_call(url, method="POST", timeout=timeout)


def batch_benchmark(
    people: List[str],
    limit_games: int = 50,
    backend_url: str = DEFAULT_BACKEND_URL,
    timeout: int = 600,
) -> List[Dict[str, Any]]:
    """
    Run benchmarks sequentially across multiple players.
    Raises ConnectionError or RuntimeError immediately if backend connection fails.
    """
    results = []
    for person in people:
        clean = person.strip().lower()
        res = benchmark_model(clean, limit_games=limit_games, backend_url=backend_url, timeout=timeout)
        results.append(res)
    return results


def format_benchmark_tables(results: List[Dict[str, Any]]) -> str:
    """
    Format benchmark results into clean GitHub-flavored markdown comparison tables:
    1. Move Prediction Performance (Baseline Maia-3 vs Clone Model)
    2. Decision Time Prediction Accuracy (Log-Normal Tempo Head vs Actual Game Clocks)
    """
    lines = []

    # Table 1: Move Prediction
    lines.append("### 1. Move Prediction Accuracy & Loss (Baseline Maia-3 vs. Clone Model)")
    lines.append("")
    lines.append("| Player | Analyzed Games | Positions | Maia Top-1 (%) | Clone Top-1 (%) | Δ Top-1 | Maia Top-3 (%) | Clone Top-3 (%) | Δ Top-3 | Maia Loss | Clone Loss | Loss Δ |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")

    for r in results:
        pid = r.get("player_id", "")
        games = r.get("games_analyzed", 0)
        pos = r.get("positions_evaluated", 0)
        mv = r.get("move_evaluation", {})

        m_top1 = mv.get("maia_top1_pct", 0.0)
        c_top1 = mv.get("clone_top1_pct", 0.0)
        d_top1 = mv.get("top1_delta_pct", 0.0)
        sign_top1 = f"+{d_top1:.2f}%" if d_top1 > 0 else f"{d_top1:.2f}%"

        m_top3 = mv.get("maia_top3_pct", 0.0)
        c_top3 = mv.get("clone_top3_pct", 0.0)
        d_top3 = mv.get("top3_delta_pct", 0.0)
        sign_top3 = f"+{d_top3:.2f}%" if d_top3 > 0 else f"{d_top3:.2f}%"

        m_loss = mv.get("maia_loss", 0.0)
        c_loss = mv.get("clone_loss", 0.0)
        l_red = mv.get("loss_reduction", 0.0)
        sign_lred = f"-{l_red:.4f}" if l_red > 0 else (f"+{abs(l_red):.4f}" if l_red < 0 else "0.0000")

        lines.append(
            f"| `{pid}` | {games} | {pos:,} | {m_top1:.2f}% | **{c_top1:.2f}%** | {sign_top1} | "
            f"{m_top3:.2f}% | **{c_top3:.2f}%** | {sign_top3} | {m_loss:.4f} | **{c_loss:.4f}** | {sign_lred} |"
        )

    lines.append("")
    lines.append("### 2. Decision Time Prediction Accuracy (Model Predictions vs. Actual Clocks)")
    lines.append("")
    lines.append("| Player | Valid Moves | Actual Med (s) | Pred Med (s) | Δ Tempo (s) | MedAE (s) | MAE (s) | Within ±2s (%) | Within ±5s (%) | Pearson r |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")

    for r in results:
        pid = r.get("player_id", "")
        tm = r.get("time_evaluation", {})
        val_moves = tm.get("valid_positions", 0)
        act_med = tm.get("actual_median_sec", 0.0)
        prd_med = tm.get("pred_median_sec", 0.0)
        tempo_delta = tm.get("median_tempo_delta_sec", 0.0)
        sign_tempo = f"+{tempo_delta:.2f}s" if tempo_delta > 0 else f"{tempo_delta:.2f}s"
        medae = tm.get("medae_sec", 0.0)
        mae = tm.get("mae_sec", 0.0)
        w2 = tm.get("within_2s_pct", 0.0)
        w5 = tm.get("within_5s_pct", 0.0)
        corr = tm.get("correlation_r", 0.0)

        lines.append(
            f"| `{pid}` | {val_moves:,} | {act_med:.2f}s | {prd_med:.2f}s | {sign_tempo} | "
            f"{medae:.2f}s | {mae:.2f}s | {w2:.1f}% | {w5:.1f}% | {corr:.3f} |"
        )

    return "\n".join(lines)
