from typing import Any, Optional
from app.db.connection import query, query_one, execute, transaction
from app.db.repositories.game_repo import format_game_row


def get_analysis_by_game(game_id: str, user_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Return cached analysis record, assembling normalized 3NF evaluation rows and tags."""
    if user_id:
        sql = "SELECT id, user_id, game_id, narrative, created_at FROM analyzed_games WHERE game_id = %s AND user_id = %s"
        base = query_one(sql, (game_id, user_id))
    else:
        sql = "SELECT id, user_id, game_id, narrative, created_at FROM analyzed_games WHERE game_id = %s ORDER BY id DESC LIMIT 1"
        base = query_one(sql, (game_id,))

    if not base:
        return None

    analysis_id = base["id"]

    eval_sql = """
        SELECT ply, win_probability, phase, headline, commentary, is_pivotal, pivotal_label
        FROM analysis_evaluations
        WHERE analysis_id = %s
        ORDER BY ply ASC
    """
    eval_rows = query(eval_sql, (analysis_id,))

    tags_sql = "SELECT tag FROM analysis_tags WHERE analysis_id = %s"
    tag_rows = query(tags_sql, (analysis_id,))

    odds = [r["win_probability"] for r in eval_rows]
    commentary = [
        {
            "ply": r["ply"],
            "phase": r.get("phase") or "Middle Game",
            "headline": r.get("headline") or "",
            "text": r.get("commentary") or "",
            "isPivotal": bool(r.get("is_pivotal")),
            "pivotalLabel": r.get("pivotal_label") or "",
        }
        for r in eval_rows
        if r.get("commentary")
    ]
    tags = [r["tag"] for r in tag_rows]

    return {
        "id": base["id"],
        "user_id": base["user_id"],
        "game_id": base["game_id"],
        "narrative": base.get("narrative") or "",
        "odds": odds,
        "commentary": commentary,
        "narrative_tags": tags,
        "created_at": base["created_at"],
    }


def save_odds(user_id: str, game_id: str, odds: list[float]) -> None:
    """Atomically upsert evaluation odds into normalized 3NF evaluation rows."""
    from app.db.repositories import user_repo
    user_id = user_repo.ensure_user_exists(user_id)

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO analyzed_games (user_id, game_id)
                VALUES (%s, %s)
                ON CONFLICT (user_id, game_id) DO UPDATE SET user_id = EXCLUDED.user_id
                RETURNING id
                """,
                (user_id, game_id),
            )
            analysis_id = cur.fetchone()["id"]

            for ply, prob in enumerate(odds, start=1):
                cur.execute(
                    """
                    INSERT INTO analysis_evaluations (analysis_id, ply, win_probability)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (analysis_id, ply)
                    DO UPDATE SET win_probability = EXCLUDED.win_probability
                    """,
                    (analysis_id, ply, float(prob)),
                )


def save_commentary_and_narrative(
    user_id: str,
    game_id: str,
    commentary: list[dict[str, Any]],
    narrative: str,
    tags: list[str],
) -> None:
    """Atomically upsert coaching narrative, tags, and move evaluations into 3NF child tables."""
    from app.db.repositories import user_repo
    user_id = user_repo.ensure_user_exists(user_id)

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO analyzed_games (user_id, game_id, narrative)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, game_id)
                DO UPDATE SET narrative = EXCLUDED.narrative
                RETURNING id
                """,
                (user_id, game_id, narrative),
            )
            analysis_id = cur.fetchone()["id"]

            for t in tags:
                clean_t = t.strip() if isinstance(t, str) else str(t)
                if clean_t:
                    cur.execute(
                        """
                        INSERT INTO analysis_tags (analysis_id, tag)
                        VALUES (%s, %s)
                        ON CONFLICT (analysis_id, tag) DO NOTHING
                        """,
                        (analysis_id, clean_t),
                    )

            for c in commentary:
                ply = c.get("ply")
                if ply is not None:
                    cur.execute(
                        """
                        INSERT INTO analysis_evaluations (
                            analysis_id, ply, win_probability, phase, headline, commentary, is_pivotal, pivotal_label
                        )
                        VALUES (%s, %s, 50.0, %s, %s, %s, %s, %s)
                        ON CONFLICT (analysis_id, ply)
                        DO UPDATE SET
                            phase = COALESCE(EXCLUDED.phase, analysis_evaluations.phase),
                            headline = COALESCE(EXCLUDED.headline, analysis_evaluations.headline),
                            commentary = COALESCE(EXCLUDED.commentary, analysis_evaluations.commentary),
                            is_pivotal = COALESCE(EXCLUDED.is_pivotal, analysis_evaluations.is_pivotal),
                            pivotal_label = COALESCE(EXCLUDED.pivotal_label, analysis_evaluations.pivotal_label)
                        """,
                        (
                            analysis_id,
                            int(ply),
                            c.get("phase"),
                            c.get("headline"),
                            c.get("text") or c.get("commentary"),
                            bool(c.get("isPivotal") or c.get("is_pivotal")),
                            c.get("pivotalLabel") or c.get("pivotal_label"),
                        ),
                    )


def get_user_analyzed_games(user_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Return paginated list of analyzed games joined with games metadata."""
    sql = """
        SELECT g.*, a.created_at as analyzed_at
        FROM analyzed_games a
        JOIN games g ON a.game_id = g.game_id
        WHERE a.user_id = %s
        ORDER BY a.created_at DESC
        LIMIT %s OFFSET %s
    """
    rows = query(sql, (user_id, limit, offset))
    return [format_game_row(r) for r in rows]


def search_analyzed_games(user_id: str, q: str) -> list[dict[str, Any]]:
    """Search analyzed games by narrative keyword, tags, opponent, or result via 3NF relational joins."""
    q_clean = f"%{q.strip().lower()}%"
    sql = """
        SELECT DISTINCT g.*, a.id as analysis_id, a.narrative, a.created_at as analyzed_at
        FROM analyzed_games a
        JOIN games g ON a.game_id = g.game_id
        LEFT JOIN analysis_tags t ON a.id = t.analysis_id
        WHERE a.user_id = %s AND (
            LOWER(COALESCE(a.narrative, '')) LIKE %s OR
            LOWER(COALESCE(t.tag, '')) LIKE %s OR
            LOWER(COALESCE(g.opponent_username, '')) LIKE %s OR
            LOWER(COALESCE(g.result, '')) LIKE %s
        )
        ORDER BY a.created_at DESC
    """
    rows = query(sql, (user_id, q_clean, q_clean, q_clean, q_clean))
    results: list[dict[str, Any]] = []
    for r in rows:
        analysis_id = r.get("analysis_id")
        tags_rows = query("SELECT tag FROM analysis_tags WHERE analysis_id = %s", (analysis_id,))
        results.append({
            **format_game_row(r),
            "narrative": r.get("narrative"),
            "tags": [t["tag"] for t in tags_rows],
        })
    return results


def save_game_embedding(user_id: str, game_id: str, embedding: list[float]) -> None:
    """Store computed dense vector embedding into analyzed_games."""
    vec_str = f"[{','.join(str(f) for f in embedding)}]"
    sql = """
        UPDATE analyzed_games
        SET embedding = %s::vector
        WHERE user_id = %s AND game_id = %s
    """
    execute(sql, (vec_str, user_id, game_id))


def search_semantic_games(user_id: str, query_embedding: list[float], limit: int = 20) -> list[dict[str, Any]]:
    """Search analyzed games using pgvector cosine distance on natural language embedding."""
    vec_str = f"[{','.join(str(f) for f in query_embedding)}]"
    sql = """
        SELECT g.*, a.id as analysis_id, a.narrative, a.created_at as analyzed_at,
               ROUND((1.0 - (a.embedding <=> %s::vector))::numeric, 4) AS similarity_score
        FROM analyzed_games a
        JOIN games g ON a.game_id = g.game_id
        WHERE a.user_id = %s AND a.embedding IS NOT NULL
        ORDER BY a.embedding <=> %s::vector
        LIMIT %s
    """
    rows = query(sql, (vec_str, user_id, vec_str, limit))
    results: list[dict[str, Any]] = []
    for r in rows:
        analysis_id = r.get("analysis_id")
        tags_rows = query("SELECT tag FROM analysis_tags WHERE analysis_id = %s", (analysis_id,))
        results.append({
            **format_game_row(r),
            "narrative": r.get("narrative"),
            "tags": [t["tag"] for t in tags_rows],
            "similarity_score": float(r.get("similarity_score") or 0.0),
        })
    return results


def find_similar_games(game_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """Find other analyzed games with closest embedding cosine similarity."""
    sql = """
        SELECT g.*, a.id as analysis_id, a.narrative, a.created_at as analyzed_at,
               ROUND((1.0 - (a.embedding <=> target.embedding))::numeric, 4) AS similarity_score
        FROM analyzed_games a
        JOIN analyzed_games target ON target.game_id = %s
        JOIN games g ON a.game_id = g.game_id
        WHERE a.game_id != %s AND a.embedding IS NOT NULL AND target.embedding IS NOT NULL
        ORDER BY a.embedding <=> target.embedding
        LIMIT %s
    """
    rows = query(sql, (game_id, game_id, limit))
    results: list[dict[str, Any]] = []
    for r in rows:
        analysis_id = r.get("analysis_id")
        tags_rows = query("SELECT tag FROM analysis_tags WHERE analysis_id = %s", (analysis_id,))
        results.append({
            **format_game_row(r),
            "narrative": r.get("narrative"),
            "tags": [t["tag"] for t in tags_rows],
            "similarity_score": float(r.get("similarity_score") or 0.0),
        })
    return results

