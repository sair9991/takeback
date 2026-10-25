import csv
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional, Tuple

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


def get_archives(username: str) -> list[str]:
    clean_user = username.strip().lower()
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
    if require_600 and time_control != "600":
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


def fetch_user_games_and_save(username: str, limit: int = 60, out_csv: Optional[Path] = None) -> Tuple[Path, list[dict]]:
    archives = get_archives(username)
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
            parsed = parse_game_chunk(pgn, username)
            if parsed:
                collected.append(parsed)
                if len(collected) >= limit:
                    break

    if not collected:
        raise ValueError(f"No valid 10-minute games found for {username}")

    if out_csv:
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(collected[0].keys()))
            writer.writeheader()
            writer.writerows(collected)

    return out_csv, collected


def fetch_user_games(username: str, limit: int = 60) -> list[dict]:
    """Fetch parsed games directly in memory without writing to disk."""
    _, games = fetch_user_games_and_save(username, limit=limit, out_csv=None)
    return games
