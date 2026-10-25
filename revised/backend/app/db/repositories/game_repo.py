from typing import Any, Optional
from app.db.connection import query, query_one


def format_game_row(row: dict[str, Any]) -> dict[str, Any]:
    """Map raw database game record into frontend card format."""
    opp = row.get("opponent_username") or "Opponent"
    parts = opp.split()
    initials = (parts[0][0] + parts[1][0]).upper() if len(parts) >= 2 else opp[:2].upper()
    gid = row.get("game_id") or str(row.get("id"))
    return {
        "id": gid,
        "player_id": row.get("player_id") or "You",
        "opponent": opp,
        "date": row.get("date") or "",
        "platform": "Chess.com" if (row.get("src") or "").lower() == "chess.com" else "Lichess",
        "initials": initials,
        "result": row.get("result"),
        "time_control": row.get("time_control"),
        "player_color": row.get("player_color"),
        "player_elo": row.get("player_elo"),
        "opponent_elo": row.get("opponent_elo"),
        "thumbnailUrl": f"/api/games/{gid}/thumbnail.svg",
    }


def get_user_games(player_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Return paginated games for a user, sorted newest first."""
    sql = """
        SELECT * FROM games
        WHERE player_id = %s
        ORDER BY date DESC, id DESC
        LIMIT %s OFFSET %s
    """
    rows = query(sql, (player_id, limit, offset))
    return [format_game_row(r) for r in rows]


def get_game_by_id(game_id: str) -> Optional[dict[str, Any]]:
    """Look up game by external game_id, falling back to integer primary key."""
    sql = "SELECT * FROM games WHERE game_id = %s"
    row = query_one(sql, (game_id,))
    # legacy games can lack string game_id
    if not row and game_id.isdigit():
        row = query_one("SELECT * FROM games WHERE id = %s", (int(game_id),))
    return row


def get_game_moves(game_id: str) -> list[dict[str, Any]]:
    """Return chronological moves for a game."""
    sql = """
        SELECT ply, side, move, time_remaining, clock_str
        FROM moves
        WHERE game_id = %s
        ORDER BY ply ASC
    """
    return query(sql, (game_id,))
