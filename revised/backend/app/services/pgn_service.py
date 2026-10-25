import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Optional

HEADERS = {
    "User-Agent": "chess-pgn-downloader/1.0 (ChessCloneApp; contact: support@chessclone.local)",
    "Accept": "application/json",
}

TAG_RE = re.compile(r'\[(\w+)\s+"([^"]*)"\]')
CLK_RE = re.compile(r"\[%clk\s+(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)\]")


def parse_clock(comment: str) -> Optional[float]:
    """'{[%clk 0:09:58.8]}' comment text -> seconds left (598.8), or None."""
    m = CLK_RE.search(comment or "")
    if not m:
        return None
    hours = int(m.group(1) or 0)
    return round(hours * 3600 + int(m.group(2)) * 60 + float(m.group(3)), 3)


def is_ten_minute_game(time_control: Optional[str]) -> bool:
    """Return True if and only if time control is 10 minutes (600 seconds base)."""
    tc = str(time_control or "").strip()
    if tc in ("600", "600+0", "600+1", "600+2", "600+5"):
        return True
    base, _, inc = tc.partition("+")
    try:
        b = float(base)
        i = float(inc or 0)
        return b == 600.0 and i <= 5.0
    except ValueError:
        return False


def _get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(3 + attempt * 2)
                continue
            if e.code == 404:
                return None
            raise
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)
    return None


def resolve_chess_com_username(username: str) -> str:
    """Resolve username, stripping Elo/rating suffix (e.g. Schwoby_1200 -> schwoby) if needed."""
    clean_user = username.strip().lower()
    url = f"https://api.chess.com/pub/player/{clean_user}/games/archives"
    data = _get_json(url)
    if data and isinstance(data, dict) and data.get("archives"):
        return clean_user
    m = re.match(r"^([a-zA-Z0-9_\-]+?)[\-_](\d{3,4})$", clean_user)
    if m:
        base_user = m.group(1)
        url_base = f"https://api.chess.com/pub/player/{base_user}/games/archives"
        data_base = _get_json(url_base)
        if data_base and isinstance(data_base, dict) and data_base.get("archives"):
            return base_user
    return clean_user


def get_archives(username: str) -> list[str]:
    clean_user = resolve_chess_com_username(username)
    url = f"https://api.chess.com/pub/player/{clean_user}/games/archives"
    data = _get_json(url)
    if not data or not isinstance(data, dict):
        return []
    return data.get("archives", [])


def fetch_month_games(archive_url: str) -> list[dict]:
    data = _get_json(archive_url)
    if not data or not isinstance(data, dict):
        return []
    return data.get("games", [])


def parse_game_chunk(chunk: str, username: str, require_600: bool = False) -> Optional[dict[str, Any]]:
    tags = dict(TAG_RE.findall(chunk))
    parts = re.split(r"\n\s*\n", chunk.strip(), maxsplit=1)
    movetext = parts[1].strip() if len(parts) > 1 else ""

    if not movetext or not CLK_RE.search(movetext):
        return None

    time_control = str(tags.get("TimeControl", "")).strip()
    if "/" in time_control:
        return None
    if require_600 and not is_ten_minute_game(time_control):
        return None

    white_raw = tags.get("White", "").strip()
    black_raw = tags.get("Black", "").strip()
    white = white_raw.lower()
    black = black_raw.lower()
    user_clean = username.strip().lower()

    if user_clean not in (white, black):
        return None

    is_white = user_clean == white
    player_color = "white" if is_white else "black"
    opponent = black_raw if is_white else white_raw
    player_elo = tags.get("WhiteElo", "") if is_white else tags.get("BlackElo", "")
    opponent_elo = tags.get("BlackElo", "") if is_white else tags.get("WhiteElo", "")

    return {
        "player_id": user_clean,
        "date": tags.get("Date", ""),
        "player_color": player_color,
        "time_control": time_control,
        "player_elo": player_elo,
        "opponent": opponent,
        "opponent_elo": opponent_elo,
        "result": tags.get("Result", ""),
        "moves": movetext,
        "movetext": movetext,
        "event": tags.get("Event", ""),
        "site": tags.get("Site", ""),
        "white": white_raw,
        "black": black_raw,
        "white_elo": tags.get("WhiteElo", ""),
        "black_elo": tags.get("BlackElo", ""),
        "termination": tags.get("Termination", ""),
    }


def fetch_user_games(username: str, limit: int = 60) -> list[dict]:
    """Fetch parsed games directly in memory from Chess.com API."""
    clean_user = username.strip().lower()
    resolved_user = resolve_chess_com_username(clean_user)
    archives = get_archives(resolved_user)
    if not archives:
        raise ValueError(f"No archives found for user: {username}")

    collected: list[dict] = []
    for arch in reversed(archives):
        if len(collected) >= limit:
            break
        raw_games = fetch_month_games(arch)
        for g in reversed(raw_games):
            pgn = g.get("pgn", "")
            if not pgn:
                continue
            parsed = parse_game_chunk(pgn, resolved_user)
            if parsed:
                # Retain the requested username for downstream model mapping
                parsed["player_id"] = clean_user
                collected.append(parsed)
                if len(collected) >= limit:
                    break

    if not collected:
        raise ValueError(f"No valid games with clock found on Chess.com for '{username}'")

    return collected
