import io
import logging
from typing import Any, Optional
import chess
import chess.pgn
from app.db.connection import query, query_one, transaction

logger = logging.getLogger(__name__)


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
    from app.db.repositories import user_repo

    target_user = (
        user_repo.get_user_by_id(player_id)
        or user_repo.get_user_by_chess_handle(player_id)
    )
    user_keys = [player_id]
    if target_user:
        user_keys.append(target_user["user_id"])
        if target_user.get("chess_com_username"):
            user_keys.append(target_user["chess_com_username"])
    user_keys = list(set(user_keys))

    sql = """
        SELECT * FROM games
        WHERE player_id = ANY(%s)
        ORDER BY date DESC, id DESC
        LIMIT %s OFFSET %s
    """
    rows = query(sql, (user_keys, limit, offset))
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


def insert_game_with_moves(
    player_id: str,
    game_id: str,
    opponent_username: str,
    player_color: str,
    player_elo: Optional[int],
    opponent_elo: Optional[int],
    result: Optional[str],
    time_control: Optional[str],
    date: str,
    moves: list[dict[str, Any]],
    src: str = "Chess.com",
) -> None:
    """Insert a game and its moves transactionally."""
    from app.db.repositories import user_repo
    player_id = user_repo.ensure_user_exists(player_id)

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO games (player_id, game_id, src, player_color, player_elo, opponent_elo, opponent_username, result, time_control, date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (game_id) DO UPDATE SET
                    player_elo = COALESCE(EXCLUDED.player_elo, games.player_elo),
                    opponent_elo = COALESCE(EXCLUDED.opponent_elo, games.opponent_elo),
                    result = COALESCE(EXCLUDED.result, games.result)
                """,
                (
                    player_id,
                    game_id,
                    src,
                    player_color,
                    player_elo,
                    opponent_elo,
                    opponent_username,
                    result,
                    time_control,
                    date,
                ),
            )
            for m in moves:
                cur.execute(
                    """
                    INSERT INTO moves (game_id, ply, side, move, time_remaining)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (game_id, ply) DO NOTHING
                    """,
                    (
                        game_id,
                        m["ply"],
                        m["side"],
                        m["move"],
                        m.get("time_remaining"),
                    ),
                )


def sync_user_games_from_chess_com(
    username: str,
    user_id: Optional[str] = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Fetch user's recent live games from Chess.com API and save them to PostgreSQL.

    Never injects mock or dummy data. Returns empty list if no games exist.
    """
    from app.services import pgn_service
    from app.db.repositories import user_repo

    clean_user = username.strip().lower()
    target_user = (
        (user_repo.get_user_by_id(user_id) if user_id else None)
        or user_repo.get_user_by_chess_handle(clean_user)
        or (user_repo.get_user_by_id(clean_user))
    )
    owner_id = target_user["user_id"] if target_user else user_repo.ensure_user_exists(user_id or clean_user, clean_user)
    archives = pgn_service.get_archives(clean_user)
    if not archives:
        return []

    saved_count = 0
    for arch in reversed(archives):
        if saved_count >= limit:
            break
        raw_games = pgn_service.fetch_month_games(arch)
        for g in reversed(raw_games):
            if saved_count >= limit:
                break
            pgn = g.get("pgn", "")
            if not pgn:
                continue

            game_url = g.get("url", "")
            game_id = game_url.rstrip("/").split("/")[-1] if game_url else None
            if not game_id or not game_id.isdigit():
                game_id = f"{clean_user}_{g.get('end_time', 0)}"

            try:
                parsed_game = chess.pgn.read_game(io.StringIO(pgn))
                if not parsed_game:
                    continue

                headers = parsed_game.headers
                white = headers.get("White", "").strip()
                black = headers.get("Black", "").strip()
                is_white = white.lower() == clean_user
                is_black = black.lower() == clean_user
                if not (is_white or is_black):
                    continue

                player_color = "white" if is_white else "black"
                opponent = black if is_white else white

                def _safe_int(val):
                    try:
                        return int(val)
                    except (ValueError, TypeError):
                        return None

                player_elo = _safe_int(headers.get("WhiteElo") if is_white else headers.get("BlackElo"))
                opponent_elo = _safe_int(headers.get("BlackElo") if is_white else headers.get("WhiteElo"))
                raw_result = headers.get("Result", "*")
                result = "draw"
                if raw_result == "1-0":
                    result = "win" if is_white else "loss"
                elif raw_result == "0-1":
                    result = "loss" if is_white else "win"
                elif raw_result == "1/2-1/2":
                    result = "draw"
                else:
                    result = raw_result
                date_str = headers.get("Date", "")
                time_control = headers.get("TimeControl", "")

                moves_data = []
                board = parsed_game.board()
                for ply, node in enumerate(parsed_game.mainline(), start=1):
                    san = node.san()
                    side = "white" if board.turn == chess.WHITE else "black"
                    clock_s = pgn_service.parse_clock(node.comment)
                    moves_data.append({
                        "ply": ply,
                        "side": side,
                        "move": san,
                        "time_remaining": clock_s,
                    })
                    board.push(node.move)

                insert_game_with_moves(
                    player_id=owner_id,
                    game_id=game_id,
                    opponent_username=opponent,
                    player_color=player_color,
                    player_elo=player_elo,
                    opponent_elo=opponent_elo,
                    result=result,
                    time_control=time_control,
                    date=date_str,
                    moves=moves_data,
                    src="Chess.com",
                )
                saved_count += 1
            except Exception as e:
                logger.warning("Failed to parse game %s: %s", game_id, e)
                continue

    return get_user_games(owner_id, limit=limit)
