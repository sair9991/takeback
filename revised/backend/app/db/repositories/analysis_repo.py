import json
from typing import Any, Optional
from app.db.connection import query, query_one, execute
from app.db.repositories.game_repo import format_game_row


def get_analysis_by_game(game_id: str, user_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Return cached odds and commentary record for a game."""
    if user_id:
        sql = "SELECT * FROM analyzed_games WHERE game_id = %s AND user_id = %s"
        return query_one(sql, (game_id, user_id))
    sql = "SELECT * FROM analyzed_games WHERE game_id = %s LIMIT 1"
    return query_one(sql, (game_id,))


def save_odds(user_id: str, game_id: str, odds: list[float]) -> None:
    """Upsert evaluation odds list into analyzed_games."""
    sql = """
        INSERT INTO analyzed_games (user_id, game_id, odds)
        VALUES (%s, %s, %s::jsonb)
        ON CONFLICT (user_id, game_id)
        DO UPDATE SET odds = EXCLUDED.odds
    """
    execute(sql, (user_id, game_id, json.dumps(odds)))


def save_commentary_and_narrative(
    user_id: str,
    game_id: str,
    commentary: list[dict[str, Any]],
    narrative: str,
    tags: list[str],
) -> None:
    """Upsert coaching commentary, narrative, and tags into analyzed_games."""
    sql = """
        INSERT INTO analyzed_games (user_id, game_id, commentary, narrative, narrative_tags)
        VALUES (%s, %s, %s::jsonb, %s, %s::jsonb)
        ON CONFLICT (user_id, game_id)
        DO UPDATE SET
            commentary = EXCLUDED.commentary,
            narrative = EXCLUDED.narrative,
            narrative_tags = EXCLUDED.narrative_tags
    """
    execute(sql, (user_id, game_id, json.dumps(commentary), narrative, json.dumps(tags)))


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
    """Search analyzed games by narrative keyword, tags, opponent, or result."""
    q_clean = f"%{q.strip().lower()}%"
    sql = """
        SELECT g.*, a.narrative, a.narrative_tags, a.created_at as analyzed_at
        FROM analyzed_games a
        JOIN games g ON a.game_id = g.game_id
        WHERE a.user_id = %s AND (
            LOWER(COALESCE(a.narrative, '')) LIKE %s OR
            LOWER(COALESCE(a.narrative_tags::text, '')) LIKE %s OR
            LOWER(COALESCE(g.opponent_username, '')) LIKE %s OR
            LOWER(COALESCE(g.result, '')) LIKE %s
        )
        ORDER BY a.created_at DESC
    """
    rows = query(sql, (user_id, q_clean, q_clean, q_clean, q_clean))
    results: list[dict[str, Any]] = []
    for r in rows:
        tags = r.get("narrative_tags")
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except json.JSONDecodeError:
                tags = []
        elif not isinstance(tags, list):
            tags = []
        results.append({
            **format_game_row(r),
            "narrative": r.get("narrative"),
            "tags": tags,
        })
    return results
