from typing import Any, Optional
from app.db.connection import query, query_one


def format_clock(seconds: Optional[float]) -> str:
    """Format clock float in seconds into standard M:SS text format."""
    if seconds is None:
        return ""
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def format_game_row(row: dict[str, Any]) -> dict[str, Any]:
    """Map raw database game record into frontend card format with derived 3NF fields."""
    opp = row.get("opponent_username") or "Opponent"
    parts = opp.split()
    initials = (parts[0][0] + parts[1][0]).upper() if len(parts) >= 2 else opp[:2].upper()
    gid = row.get("game_id") or str(row.get("id"))
    player_color = (row.get("player_color") or "white").lower()
    opponent_color = "black" if player_color == "white" else "white"

    return {
        "id": gid,
        "player_id": row.get("player_id") or "You",
        "opponent": opp,
        "date": row.get("date") or "",
        "platform": "Chess.com" if (row.get("src") or "").lower() == "chess.com" else "Lichess",
        "initials": initials,
        "result": row.get("result"),
        "time_control": row.get("time_control"),
        "player_color": player_color,
        "opponent_color": opponent_color,
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
    if not row and game_id.isdigit():
        row = query_one("SELECT * FROM games WHERE id = %s", (int(game_id),))
    return row


def get_game_moves(game_id: str) -> list[dict[str, Any]]:
    """Return chronological moves for a game with dynamically derived clock string."""
    sql = """
        SELECT ply, side, move, time_remaining
        FROM moves
        WHERE game_id = %s
        ORDER BY ply ASC
    """
    rows = query(sql, (game_id,))
    return [
        {
            "ply": r["ply"],
            "side": r["side"],
            "move": r["move"],
            "time_remaining": r["time_remaining"],
            "clock_str": format_clock(r["time_remaining"]),
        }
        for r in rows
    ]
