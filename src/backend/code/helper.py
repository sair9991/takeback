import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "database" / "mock_db.db"


def query(sql: str, params: tuple = ()):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def query_one(sql: str, params: tuple = ()):
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple = ()):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return cur.lastrowid


def format_game(row: dict) -> dict:
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
